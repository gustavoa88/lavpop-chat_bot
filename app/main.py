import hashlib
import hmac
import json
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse
import logging

from app.config import load_settings
from app.db import Database
from app.services import ChatService, normalize_phone

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("meta_chatbot")

settings = load_settings()
db = Database(settings)
chat_service = ChatService(db, settings)
_meta_signature_secret_missing_logged = False

app = FastAPI(title="Meta WhatsApp Chatbot", version="1.0.0")


@app.on_event("startup")
async def startup_event() -> None:
    db.start()
    if settings.meta_validate_signature and not settings.meta_app_secret:
        logger.warning(
            "Validação de assinatura Meta está ativa, mas META_APP_SECRET não foi configurado. "
            "A validação será ignorada até o segredo ser definido."
        )
    logger.info("Aplicação iniciada com sucesso.")


@app.on_event("shutdown")
async def shutdown_event() -> None:
    db.stop()
    logger.info("Aplicação finalizada com sucesso.")


@app.get("/")
async def healthcheck() -> dict:
    return {"status": "ok", "service": "meta-chatbot"}


def _validate_webhook_request(request: Request) -> str:
    mode = request.query_params.get("hub.mode")
    verify_token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    logger.info(
        "Recebida tentativa de verificação do webhook. mode=%s token_recebido=%s",
        mode,
        verify_token,
    )

    if mode == "subscribe" and verify_token == settings.meta_verify_token and challenge:
        return challenge

    raise HTTPException(status_code=403, detail="Falha na verificação do webhook")


def _validate_meta_signature(request: Request, body: bytes) -> None:
    global _meta_signature_secret_missing_logged

    if not settings.meta_validate_signature:
        return

    app_secret = (settings.meta_app_secret or "").strip()
    if not app_secret:
        if not _meta_signature_secret_missing_logged:
            logger.warning(
                "META_APP_SECRET ausente: validação HMAC do webhook está sendo ignorada "
                "(modo compatibilidade). Configure o segredo para ativar validação real."
            )
            _meta_signature_secret_missing_logged = True
        return

    signature = (request.headers.get("X-Hub-Signature-256") or "").strip()
    if not signature.startswith("sha256="):
        raise HTTPException(status_code=403, detail="Assinatura do webhook ausente ou inválida")

    expected = "sha256=" + hmac.new(app_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise HTTPException(status_code=403, detail="Assinatura do webhook inválida")


@app.get("/webhook")
async def verify_webhook_root(request: Request):
    challenge = _validate_webhook_request(request)
    return PlainTextResponse(content=challenge)


@app.get("/webhook/meta")
async def verify_webhook_meta(request: Request):
    challenge = _validate_webhook_request(request)
    return PlainTextResponse(content=challenge)


async def _process_meta_webhook(request: Request) -> dict:
    raw_body = await request.body()
    _validate_meta_signature(request, raw_body)

    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Payload JSON inválido") from exc

    logger.info("Webhook recebido: %s", payload)

    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            contacts = value.get("contacts", [])
            messages = value.get("messages", [])

            contact_name = ""
            if contacts:
                contact_name = ((contacts[0].get("profile") or {}).get("name") or "").strip()

            for message_obj in messages:
                try:
                    msg_type = (message_obj.get("type") or "").strip().lower()
                    phone = normalize_phone((message_obj.get("from") or "").strip())

                    if msg_type == "text":
                        incoming_text = ((message_obj.get("text") or {}).get("body") or "").strip()
                    elif msg_type == "button":
                        incoming_text = ((message_obj.get("button") or {}).get("text") or "").strip()
                    else:
                        incoming_text = ""

                    if not incoming_text or not phone:
                        logger.info(
                            "Mensagem ignorada. type=%s phone=%s text=%s",
                            msg_type,
                            phone,
                            incoming_text,
                        )
                        continue

                    logger.info(
                        "Mensagem recebida de %s (%s): %s",
                        contact_name,
                        phone,
                        incoming_text,
                    )

                    answer, _, _, _ = chat_service.answer_message(phone, contact_name, incoming_text)
                    chat_service.send_meta_message(phone, answer)
                except Exception:
                    logger.exception("Falha ao processar mensagem do webhook para contato=%s", contact_name)
                    continue

    return {"status": "ok"}


@app.post("/webhook")
async def receive_meta_webhook_root(request: Request) -> dict:
    return await _process_meta_webhook(request)


@app.post("/webhook/meta")
async def receive_meta_webhook_meta(request: Request) -> dict:
    return await _process_meta_webhook(request)
