import hashlib
import json
from collections import defaultdict, deque
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse
import logging
from starlette.concurrency import run_in_threadpool
from starlette.staticfiles import StaticFiles
import psycopg2

from app.config import load_settings
from app.conversation_router import BOT_ACTION, HANDOFF_ACTION, REGISTER_ONLY_ACTION, ConversationRouter
from app.db import Database
from app.network_security import enforce_internal_observability_access
from app.network_security import resolve_request_ip
from app.observability import ObservabilityState, build_prometheus_metrics
from app.operator_panel import create_operator_router
from app.services import ChatService, PROACTIVE_MENU_MESSAGE
from app.webhook_parser import ParsedMessageEvent
from app.webhook_parser import parse_meta_message_events
from app.webhook_security import (
    build_message_event_key,
    validate_meta_signature,
    validate_webhook_challenge,
)

load_dotenv()

settings = load_settings()
logging.basicConfig(
    level=getattr(logging, settings.log_level, logging.INFO),
    format="%(levelname)s:%(name)s:%(message)s",
)
logger = logging.getLogger("meta_chatbot")
db = Database(settings)
chat_service = ChatService(db, settings)
conversation_router = ConversationRouter()
_meta_signature_secret_missing_logged = False


def _is_production() -> bool:
    return settings.app_env in {"prod", "production"}


observability_state = ObservabilityState()


class _WebhookRateLimiter:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._hits_by_key: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str, *, now: float, limit_per_minute: int) -> bool:
        if limit_per_minute <= 0:
            return True

        window_started_at = now - 60
        with self._lock:
            hits = self._hits_by_key[key]
            while hits and hits[0] <= window_started_at:
                hits.popleft()
            if len(hits) >= limit_per_minute:
                return False
            hits.append(now)
            return True


webhook_rate_limiter = _WebhookRateLimiter()


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
    if settings.app_debug_log_mode and not _is_production():
        logger.info("[debug_log_mode] " + message, *args)


def _is_db_not_initialized_error(exc: Exception) -> bool:
    return isinstance(exc, RuntimeError) and str(exc) == "Database pool not initialized"


def _is_optional_persistence_schema_error(exc: Exception) -> bool:
    return isinstance(
        exc,
        (
            psycopg2.errors.UndefinedTable,
            psycopg2.errors.UndefinedColumn,
        ),
    )


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
        if _is_optional_persistence_schema_error(exc):
            logger.warning(
                "Persistência opcional indisponível (%s) por schema incompleto; "
                "aplique db/schema.sql ou reinicie a aplicação para criar objetos mínimos.",
                operation,
            )
            return None
        raise


def _enforce_production_security_baseline() -> None:
    if not _is_production():
        return

    required_settings = {
        "META_VERIFY_TOKEN": settings.meta_verify_token,
        "META_WHATSAPP_TOKEN": settings.meta_whatsapp_token,
        "META_PHONE_NUMBER_ID": settings.meta_phone_number_id,
    }
    missing_settings = [
        name for name, value in required_settings.items() if not (value or "").strip()
    ]
    if missing_settings:
        raise RuntimeError(
            "Em produção (APP_ENV=prod|production), as configurações obrigatórias "
            f"estão ausentes: {', '.join(missing_settings)}."
        )
    if not settings.meta_validate_signature:
        raise RuntimeError(
            "Em produção (APP_ENV=prod|production), META_VALIDATE_SIGNATURE deve ser true "
            "para validar a assinatura HMAC do webhook."
        )
    if not settings.meta_require_app_secret:
        raise RuntimeError(
            "Em produção (APP_ENV=prod|production), META_REQUIRE_APP_SECRET deve ser true "
            "para impedir modo compatibilidade sem validação HMAC estrita."
        )
    if not (settings.meta_app_secret or "").strip():
        raise RuntimeError(
            "Em produção (APP_ENV=prod|production), META_APP_SECRET é obrigatório "
            "para validar a assinatura HMAC do webhook."
        )
    if settings.app_debug_log_mode:
        raise RuntimeError(
            "Em produção (APP_ENV=prod|production), APP_DEBUG_LOG_MODE deve ser false "
            "para evitar logs com payload bruto do webhook."
        )
    if settings.operator_panel_enabled and not settings.operator_panel_token:
        raise RuntimeError(
            "Em produção (APP_ENV=prod|production), OPERATOR_PANEL_TOKEN é obrigatório "
            "quando OPERATOR_PANEL_ENABLED=true."
        )


def _enforce_internal_observability_access(request: Request) -> None:
    """Mantém regra de acesso interno, delegando para módulo especializado."""
    enforce_internal_observability_access(
        request=request,
        observability_internal_only=settings.observability_internal_only,
        trust_proxy_headers=settings.trust_proxy_headers,
        trusted_proxy_cidrs=settings.trusted_proxy_cidrs,
    )


def _enforce_webhook_rate_limit(request: Request) -> None:
    request_ip = resolve_request_ip(
        request=request,
        trust_proxy_headers=settings.trust_proxy_headers,
        trusted_proxy_cidrs=settings.trusted_proxy_cidrs,
    )
    allowed = webhook_rate_limiter.allow(
        request_ip or "unknown",
        now=time.time(),
        limit_per_minute=settings.webhook_rate_limit_per_minute,
    )
    if not allowed:
        logger.warning("Webhook bloqueado por rate limit. ip=%s", request_ip or "unknown")
        raise HTTPException(status_code=429, detail="Rate limit excedido")


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

    _enforce_production_security_baseline()
    db.start()
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

app = FastAPI(
    title="Meta WhatsApp Chatbot",
    version="1.0.0",
    lifespan=lifespan,
    docs_url=None if _is_production() else "/docs",
    redoc_url=None if _is_production() else "/redoc",
    openapi_url=None if _is_production() else "/openapi.json",
)

if settings.operator_panel_enabled:
    app.mount(
        "/operator/static",
        StaticFiles(directory=str(Path(__file__).resolve().parent / "static")),
        name="operator_static",
    )
    app.include_router(create_operator_router(chat_service, settings))


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
    db_health = db.healthcheck()
    return PlainTextResponse(
        content=build_prometheus_metrics(
            observability_state.snapshot(),
            db_health["ready"],
            db_health["latency_ms"],
        )
    )


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

    try:
        validate_meta_signature(
            request=request,
            body=body,
            validate_signature=settings.meta_validate_signature,
            app_secret=settings.meta_app_secret,
        )
    except HTTPException:
        observability_state.mark_signature_failure()
        observability_state.mark_error_type("signature_failure")
        raise


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

        observability_state.mark_response_source("roteador")
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

    observability_state.mark_response_source(source)
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
    _enforce_webhook_rate_limit(request)
    observability_state.mark_webhook()
    started_at = time.perf_counter()
    raw_body = await request.body()
    _validate_meta_signature(request, raw_body)
    payload_hash = hashlib.sha256(raw_body).hexdigest()

    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        observability_state.mark_error()
        observability_state.mark_error_type("invalid_json")
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
                observability_state.mark_error_type(result)
            logger.info(
                "Resultado do processamento do webhook. result=%s type=%s phone=%s payload_hash=%s",
                result,
                event.msg_type,
                _phone_log_id(event.phone),
                payload_hash[:12],
            )
        except Exception:
            logger.exception(
                "Falha ao processar mensagem do webhook. phone=%s type=%s",
                _phone_log_id(event.phone),
                event.msg_type,
            )
            observability_state.mark_error()
            observability_state.mark_error_type("exception")
            continue

    observability_state.set_last_processing_seconds(time.perf_counter() - started_at)
    return {"status": "ok"}


@app.post("/webhook")
async def receive_meta_webhook_root(request: Request) -> dict:
    return await _process_meta_webhook(request)


@app.post("/webhook/meta")
async def receive_meta_webhook_meta(request: Request) -> dict:
    return await _process_meta_webhook(request)
