import hashlib
import json
import threading
import time
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse
import logging
from starlette.concurrency import run_in_threadpool

from app.config import load_settings
from app.conversation_router import BOT_ACTION, HANDOFF_ACTION, REGISTER_ONLY_ACTION, ConversationRouter
from app.db import Database
from app.network_security import enforce_internal_observability_access
from app.observability import ObservabilityState, build_prometheus_metrics
from app.services import ChatService, PROACTIVE_MENU_MESSAGE
from app.webhook_parser import ParsedMessageEvent
from app.webhook_parser import parse_meta_message_events
from app.webhook_security import (
    build_message_event_key,
    validate_meta_signature,
    validate_webhook_challenge,
)

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("meta_chatbot")

settings = load_settings()
db = Database(settings)
chat_service = ChatService(db, settings)
conversation_router = ConversationRouter()
_meta_signature_secret_missing_logged = False


class _ObservabilityState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.webhook_total = 0
        self.messages_processed_total = 0
        self.messages_recorded_total = 0
        self.messages_ignored_total = 0
        self.messages_duplicate_total = 0
        self.processing_errors_total = 0
        self.last_processing_seconds = 0.0

    def mark_webhook(self) -> None:
        with self._lock:
            self.webhook_total += 1

    def mark_processed(self) -> None:
        with self._lock:
            self.messages_processed_total += 1

    def mark_recorded(self) -> None:
        with self._lock:
            self.messages_recorded_total += 1

    def mark_ignored(self) -> None:
        with self._lock:
            self.messages_ignored_total += 1

    def mark_duplicate(self) -> None:
        with self._lock:
            self.messages_duplicate_total += 1

    def mark_error(self) -> None:
        with self._lock:
            self.processing_errors_total += 1

    def set_last_processing_seconds(self, seconds: float) -> None:
        with self._lock:
            self.last_processing_seconds = seconds

    def snapshot(self) -> dict[str, float]:
        with self._lock:
            return {
                "webhook_total": float(self.webhook_total),
                "messages_processed_total": float(self.messages_processed_total),
                "messages_recorded_total": float(self.messages_recorded_total),
                "messages_ignored_total": float(self.messages_ignored_total),
                "messages_duplicate_total": float(self.messages_duplicate_total),
                "processing_errors_total": float(self.processing_errors_total),
                "last_processing_seconds": self.last_processing_seconds,
            }


observability_state = _ObservabilityState()


def _phone_log_id(phone: str) -> str:
    phone = (phone or "").strip()
    if not phone:
        return "ausente"
    return f"phone_hash:{hashlib.sha256(phone.encode('utf-8')).hexdigest()[:12]}"


def _message_preview(message: str, limit: int = 80) -> str:
    compact = " ".join((message or "").split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + "..."


def _debug_log(message: str, *args) -> None:
    if settings.app_debug_log_mode:
        logger.info("[debug_log_mode] " + message, *args)


def _is_db_not_initialized_error(exc: Exception) -> bool:
    return isinstance(exc, RuntimeError) and str(exc) == "Database pool not initialized"


def _best_effort_persistence(operation: str, fn):
    try:
        return fn()
    except Exception as exc:
        if _is_db_not_initialized_error(exc):
            logger.warning(
                "Persistência indisponível (%s) por pool de banco não inicializado; seguindo processamento.",
                operation,
            )
            return None
        raise


def _enforce_production_security_baseline() -> None:
    if settings.app_env in {"prod", "production"} and not settings.meta_require_app_secret:
        raise RuntimeError(
            "Em produção (APP_ENV=prod|production), META_REQUIRE_APP_SECRET deve ser true "
            "para impedir modo compatibilidade sem validação HMAC estrita."
        )


def _enforce_internal_observability_access(request: Request) -> None:
    """Mantém regra de acesso interno, delegando para módulo especializado."""
    enforce_internal_observability_access(
        request=request,
        observability_internal_only=settings.observability_internal_only,
        trust_proxy_headers=settings.trust_proxy_headers,
        trusted_proxy_cidrs=settings.trusted_proxy_cidrs,
    )


def _run_inactivity_watcher(stop_event: threading.Event) -> None:
    interval_seconds = max(10, settings.inactivity_check_interval_seconds)
    while not stop_event.wait(interval_seconds):
        try:
            closed_count = chat_service.close_inactive_conversations()
            if closed_count:
                logger.info(
                    "Encerramento automático por inatividade executado. conversas_encerradas=%s",
                    closed_count,
                )
        except Exception:
            logger.exception("Falha no watcher de encerramento por inatividade.")


@asynccontextmanager
async def lifespan(_: FastAPI):
    inactivity_stop_event = threading.Event()
    inactivity_worker = threading.Thread(
        target=_run_inactivity_watcher,
        args=(inactivity_stop_event,),
        name="inactivity-watcher",
        daemon=True,
    )

    db.start()
    _enforce_production_security_baseline()
    if settings.meta_validate_signature and not settings.meta_app_secret:
        if settings.meta_require_app_secret:
            raise RuntimeError(
                "META_APP_SECRET é obrigatório quando META_VALIDATE_SIGNATURE=true e "
                "META_REQUIRE_APP_SECRET=true. Defina o segredo ou desative o modo estrito."
            )
        logger.warning(
            "Validação de assinatura Meta está ativa, mas META_APP_SECRET não foi configurado. "
            "A validação será ignorada até o segredo ser definido."
        )
    inactivity_worker.start()
    logger.info("Aplicação iniciada com sucesso.")
    try:
        yield
    finally:
        inactivity_stop_event.set()
        inactivity_worker.join(timeout=2)
        db.stop()
        logger.info("Aplicação finalizada com sucesso.")

app = FastAPI(title="Meta WhatsApp Chatbot", version="1.0.0", lifespan=lifespan)


@app.get("/")
async def healthcheck() -> dict:
    return {"status": "ok", "service": "meta-chatbot"}


@app.get("/health/live")
async def health_live(request: Request) -> dict:
    _enforce_internal_observability_access(request)
    return {"status": "alive", "service": "meta-chatbot"}


@app.get("/health/ready")
async def health_ready(request: Request) -> dict:
    _enforce_internal_observability_access(request)
    if not db.is_ready():
        raise HTTPException(
            status_code=503,
            detail="Banco de dados indisponível",
        )
    return {"status": "ready", "dependencies": {"database": "ok"}}


@app.get("/health/db")
async def health_db(request: Request) -> dict:
    _enforce_internal_observability_access(request)
    db_health = db.healthcheck()
    if not db_health["ready"]:
        raise HTTPException(
            status_code=503,
            detail={
                "status": "down",
                "database": db_health,
            },
        )
    return {"status": "up", "database": db_health}


@app.get("/metrics")
async def metrics(request: Request) -> PlainTextResponse:
    _enforce_internal_observability_access(request)
    metrics_snapshot = observability_state.snapshot()
    db_health = db.healthcheck()
    db_ready = 1 if db_health["ready"] else 0
    db_latency_ms = db_health["latency_ms"]

    lines = [
        "# HELP chatbot_webhook_requests_total Total de webhooks recebidos.",
        "# TYPE chatbot_webhook_requests_total counter",
        f"chatbot_webhook_requests_total {int(metrics_snapshot['webhook_total'])}",
        "# HELP chatbot_messages_processed_total Total de mensagens processadas com resposta.",
        "# TYPE chatbot_messages_processed_total counter",
        f"chatbot_messages_processed_total {int(metrics_snapshot['messages_processed_total'])}",
        "# HELP chatbot_messages_recorded_total Total de mensagens registradas sem resposta automática.",
        "# TYPE chatbot_messages_recorded_total counter",
        f"chatbot_messages_recorded_total {int(metrics_snapshot['messages_recorded_total'])}",
        "# HELP chatbot_messages_ignored_total Total de mensagens ignoradas por payload inválido.",
        "# TYPE chatbot_messages_ignored_total counter",
        f"chatbot_messages_ignored_total {int(metrics_snapshot['messages_ignored_total'])}",
        "# HELP chatbot_messages_duplicate_total Total de mensagens descartadas por idempotência.",
        "# TYPE chatbot_messages_duplicate_total counter",
        f"chatbot_messages_duplicate_total {int(metrics_snapshot['messages_duplicate_total'])}",
        "# HELP chatbot_message_processing_errors_total Total de erros no processamento de mensagens.",
        "# TYPE chatbot_message_processing_errors_total counter",
        f"chatbot_message_processing_errors_total {int(metrics_snapshot['processing_errors_total'])}",
        "# HELP chatbot_webhook_last_processing_seconds Duração do último processamento de webhook.",
        "# TYPE chatbot_webhook_last_processing_seconds gauge",
        f"chatbot_webhook_last_processing_seconds {metrics_snapshot['last_processing_seconds']:.6f}",
        "# HELP chatbot_database_ready Estado do banco (1=up, 0=down).",
        "# TYPE chatbot_database_ready gauge",
        f"chatbot_database_ready {db_ready}",
        "# HELP chatbot_database_latency_ms Latência do check de banco em milissegundos.",
        "# TYPE chatbot_database_latency_ms gauge",
        f"chatbot_database_latency_ms {db_latency_ms}",
    ]

    return PlainTextResponse(content="\n".join(lines) + "\n")


def _validate_webhook_request(request: Request) -> str:
    mode = request.query_params.get("hub.mode")
    verify_token = request.query_params.get("hub.verify_token")
    logger.info(
        "Recebida tentativa de verificação do webhook. mode=%s token_presente=%s",
        mode,
        bool(verify_token),
    )
    return validate_webhook_challenge(request, settings.meta_verify_token)


def _validate_meta_signature(request: Request, body: bytes) -> None:
    global _meta_signature_secret_missing_logged

    if settings.meta_validate_signature and not (settings.meta_app_secret or "").strip():
        if not _meta_signature_secret_missing_logged:
            logger.warning(
                "META_APP_SECRET ausente: validação HMAC do webhook está sendo ignorada "
                "(modo compatibilidade). Configure o segredo para ativar validação real."
            )
            _meta_signature_secret_missing_logged = True
        return

    validate_meta_signature(
        request=request,
        body=body,
        validate_signature=settings.meta_validate_signature,
        app_secret=settings.meta_app_secret,
    )


def _build_message_event_key(message_obj: dict, phone: str, incoming_text: str, msg_type: str) -> str:
    return build_message_event_key(message_obj, phone, incoming_text, msg_type)


def _payload_summary(payload: dict) -> dict[str, int]:
    entries = payload.get("entry", [])
    changes_count = 0
    messages_count = 0
    for entry in entries:
        changes = entry.get("changes", [])
        changes_count += len(changes)
        for change in changes:
            value = change.get("value", {})
            messages_count += len(value.get("messages", []))

    return {
        "entries": len(entries),
        "changes": changes_count,
        "messages": messages_count,
    }


def _send_answer(phone: str, answer: str) -> bool:
    if answer == PROACTIVE_MENU_MESSAGE:
        sent = chat_service.send_meta_menu_message(phone)
        if sent:
            return True
        logger.info("Fallback para mensagem de texto após falha no menu interativo. destino=%s", _phone_log_id(phone))
        return chat_service.send_meta_message(phone, answer)

    return chat_service.send_meta_message(phone, answer)


def _handle_meta_message_event(event: ParsedMessageEvent, payload_hash: str) -> str:
    message_obj = event.message_obj
    msg_type = event.msg_type
    phone = event.phone
    incoming_text = event.incoming_text
    contact_name = event.contact_name
    phone_log_id = _phone_log_id(phone)

    if not incoming_text or not phone:
        logger.info(
            "Mensagem ignorada por payload incompleto. type=%s phone=%s text_present=%s",
            msg_type,
            phone_log_id,
            bool(incoming_text),
        )
        return "ignored"

    event_key = _build_message_event_key(message_obj, phone, incoming_text, msg_type)
    is_new_event = db.try_register_webhook_event(
        event_key=event_key,
        payload_hash=payload_hash,
        source="meta_webhook_message",
    )
    if not is_new_event:
        logger.info(
            "Mensagem duplicada ignorada por idempotência. event_key=%s phone=%s",
            event_key,
            phone_log_id,
        )
        return "duplicate"

    logger.info(
        "Mensagem recebida. event_key=%s type=%s phone=%s contact_name_present=%s preview=%s",
        event_key,
        msg_type,
        phone_log_id,
        bool(contact_name),
        _message_preview(incoming_text),
    )

    _best_effort_persistence(
        "save_message_inbound",
        lambda: chat_service.save_message(
            event_key=event_key,
            phone=phone,
            name=contact_name,
            direction="inbound",
            origin="cliente",
            message_type=msg_type,
            text=incoming_text,
            payload=message_obj,
            status="received",
        ),
    )
    _best_effort_persistence(
        "touch_inbound_context",
        lambda: chat_service.touch_inbound_context(phone, contact_name, source="cliente"),
    )

    context = _best_effort_persistence("get_customer_context", lambda: chat_service.get_customer_context(phone)) or {}
    decision = conversation_router.decide(incoming_text, context)
    _debug_log(
        "Decisão do roteador. event_key=%s mode_anterior=%s mode_novo=%s action=%s reason=%s",
        event_key,
        (context.get("modo_conversa") or "bot"),
        decision.mode,
        decision.action,
        decision.reason,
    )
    if decision.mode != (context.get("modo_conversa") or "bot"):
        _best_effort_persistence(
            "set_conversation_mode",
            lambda: chat_service.set_conversation_mode(phone, contact_name, decision.mode, decision.reason),
        )

    if decision.action == REGISTER_ONLY_ACTION:
        logger.info(
            "Mensagem registrada sem resposta automática. event_key=%s phone=%s mode=%s reason=%s",
            event_key,
            phone_log_id,
            decision.mode,
            decision.reason,
        )
        return "recorded"

    if decision.action == HANDOFF_ACTION:
        answer = decision.answer or ""
        _best_effort_persistence(
            "save_log_handoff",
            lambda: chat_service.save_log(
                phone=phone,
                name=contact_name,
                client_msg=incoming_text,
                bot_msg=answer,
                source="roteador",
                rule_name=decision.reason,
            ),
        )
        sent = _send_answer(phone, answer)
        _best_effort_persistence(
            "save_message_outbound_handoff",
            lambda: chat_service.save_message(
                phone=phone,
                name=contact_name,
                direction="outbound",
                origin="bot",
                text=answer,
                status="sent" if sent else "send_failed",
                response_source="roteador",
                rule_name=decision.reason,
                intent="handoff_humano",
            ),
        )
        if not sent:
            logger.error(
                "Aviso de handoff gerado, mas envio para Meta falhou. event_key=%s phone=%s reason=%s",
                event_key,
                phone_log_id,
                decision.reason,
            )
            return "send_failed"

        logger.info(
            "Conversa roteada para humano. event_key=%s phone=%s mode=%s reason=%s",
            event_key,
            phone_log_id,
            decision.mode,
            decision.reason,
        )
        return "processed"

    if decision.action != BOT_ACTION:
        logger.error(
            "Roteador retornou ação desconhecida. event_key=%s phone=%s action=%s",
            event_key,
            phone_log_id,
            decision.action,
        )
        return "routing_error"

    answer, source, rule_name, intent = chat_service.answer_message(phone, contact_name, incoming_text)
    sent = _send_answer(phone, answer)
    _best_effort_persistence(
        "save_message_outbound_bot",
        lambda: chat_service.save_message(
            phone=phone,
            name=contact_name,
            direction="outbound",
            origin="bot",
            text=answer,
            status="sent" if sent else "send_failed",
            response_source=source,
            rule_name=rule_name,
            intent=intent,
        ),
    )
    if not sent:
        logger.error(
            "Resposta gerada, mas envio para Meta falhou. event_key=%s phone=%s source=%s rule=%s intent=%s",
            event_key,
            phone_log_id,
            source,
            rule_name,
            intent,
        )
        return "send_failed"

    logger.info(
        "Mensagem processada com sucesso. event_key=%s phone=%s source=%s rule=%s intent=%s",
        event_key,
        phone_log_id,
        source,
        rule_name,
        intent,
    )
    return "processed"


@app.get("/webhook")
async def verify_webhook_root(request: Request):
    challenge = _validate_webhook_request(request)
    return PlainTextResponse(content=challenge)


@app.get("/webhook/meta")
async def verify_webhook_meta(request: Request):
    challenge = _validate_webhook_request(request)
    return PlainTextResponse(content=challenge)


async def _process_meta_webhook(request: Request) -> dict:
    observability_state.mark_webhook()
    started_at = time.perf_counter()
    raw_body = await request.body()
    _validate_meta_signature(request, raw_body)
    payload_hash = hashlib.sha256(raw_body).hexdigest()

    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Payload JSON inválido") from exc

    logger.info("Webhook recebido. summary=%s payload_hash=%s", _payload_summary(payload), payload_hash[:12])
    _debug_log("Webhook bruto (preview): %s", _message_preview(raw_body.decode("utf-8", errors="replace"), limit=400))

    for event in parse_meta_message_events(payload):
        _debug_log(
            "Evento parseado. type=%s phone=%s text_preview=%s keys=%s",
            event.msg_type,
            _phone_log_id(event.phone),
            _message_preview(event.incoming_text),
            sorted(list(event.message_obj.keys())),
        )
        try:
            result = await run_in_threadpool(_handle_meta_message_event, event, payload_hash)
            if result == "processed":
                observability_state.mark_processed()
            elif result == "ignored":
                observability_state.mark_ignored()
            elif result == "duplicate":
                observability_state.mark_duplicate()
            elif result == "recorded":
                observability_state.mark_recorded()
            else:
                observability_state.mark_error()
        except Exception:
            logger.exception(
                "Falha ao processar mensagem do webhook. phone=%s type=%s",
                _phone_log_id(event.phone),
                event.msg_type,
            )
            observability_state.mark_error()
            continue

    observability_state.set_last_processing_seconds(time.perf_counter() - started_at)
    return {"status": "ok"}


@app.post("/webhook")
async def receive_meta_webhook_root(request: Request) -> dict:
    return await _process_meta_webhook(request)


@app.post("/webhook/meta")
async def receive_meta_webhook_meta(request: Request) -> dict:
    return await _process_meta_webhook(request)
