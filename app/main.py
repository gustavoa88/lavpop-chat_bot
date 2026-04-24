import hashlib
import json
import threading
import time
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse
import logging

from app.config import load_settings
from app.db import Database
from app.network_security import enforce_internal_observability_access
from app.observability import ObservabilityState, build_prometheus_metrics
from app.services import ChatService, PROACTIVE_MENU_MESSAGE
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
_meta_signature_secret_missing_logged = False


observability_state = ObservabilityState()


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
    metrics_payload = build_prometheus_metrics(
        snapshot=metrics_snapshot,
        db_ready=db_health["ready"],
        db_latency_ms=db_health["latency_ms"],
    )
    return PlainTextResponse(content=metrics_payload)


def _validate_webhook_request(request: Request) -> str:
    mode = request.query_params.get("hub.mode")
    verify_token = request.query_params.get("hub.verify_token")
    logger.info(
        "Recebida tentativa de verificação do webhook. mode=%s token_recebido=%s",
        mode,
        verify_token,
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

    logger.info("Webhook recebido: %s", payload)

    for event in parse_meta_message_events(payload):
        try:
            message_obj = event.message_obj
            msg_type = event.msg_type
            phone = event.phone
            incoming_text = event.incoming_text
            contact_name = event.contact_name

            if not incoming_text or not phone:
                logger.info(
                    "Mensagem ignorada. type=%s phone=%s text=%s",
                    msg_type,
                    phone,
                    incoming_text,
                )
                observability_state.mark_ignored()
                continue

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
                    phone,
                )
                observability_state.mark_duplicate()
                continue

            logger.info(
                "Mensagem recebida de %s (%s): %s",
                contact_name,
                phone,
                incoming_text,
            )

            answer, _, _, _ = chat_service.answer_message(phone, contact_name, incoming_text)
            if answer == PROACTIVE_MENU_MESSAGE:
                sent = chat_service.send_meta_menu_message(phone)
                if not sent:
                    chat_service.send_meta_message(phone, answer)
            else:
                chat_service.send_meta_message(phone, answer)
            observability_state.mark_processed()
        except Exception:
            logger.exception("Falha ao processar mensagem do webhook para contato=%s", event.contact_name)
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
