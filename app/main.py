from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response

from app.config import load_settings
from app.db import Database
from app.services import ChatService, normalize_phone

load_dotenv()

settings = load_settings()
db = Database(settings)
chat_service = ChatService(db, settings)

app = FastAPI(title="Meta WhatsApp Chatbot", version="1.0.0")


@app.on_event("startup")
async def startup_event() -> None:
    db.start()


@app.on_event("shutdown")
async def shutdown_event() -> None:
    db.stop()


@app.get("/")
async def healthcheck() -> dict:
    return {"status": "ok", "service": "meta-chatbot"}


@app.get("/webhook/meta")
async def verify_webhook(request: Request):
    mode = request.query_params.get("hub.mode")
    verify_token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    if mode == "subscribe" and verify_token == settings.meta_verify_token and challenge:
        return Response(content=challenge, media_type="text/plain")

    raise HTTPException(status_code=403, detail="Falha na verificação do webhook")


@app.post("/webhook/meta")
async def receive_meta_webhook(request: Request) -> dict:
    payload = await request.json()

    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            contacts = value.get("contacts", [])
            messages = value.get("messages", [])

            contact_name = ""
            if contacts:
                contact_name = ((contacts[0].get("profile") or {}).get("name") or "").strip()

            for message_obj in messages:
                msg_type = (message_obj.get("type") or "").strip()
                phone = normalize_phone((message_obj.get("from") or "").strip())

                if msg_type == "text":
                    incoming_text = ((message_obj.get("text") or {}).get("body") or "").strip()
                elif msg_type == "button":
                    incoming_text = ((message_obj.get("button") or {}).get("text") or "").strip()
                else:
                    incoming_text = ""

                if not incoming_text or not phone:
                    continue

                answer, _, _, _ = chat_service.answer_message(phone, contact_name, incoming_text)
                chat_service.send_meta_message(phone, answer)

    return {"status": "ok"}
