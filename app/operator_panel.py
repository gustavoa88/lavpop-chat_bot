from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from starlette.templating import Jinja2Templates

from app.config import Settings
from app.network_security import enforce_internal_observability_access
from app.services import ChatService, normalize_phone


TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))


class HumanMessageRequest(BaseModel):
    text: str


def _require_operator_access(request: Request, settings: Settings) -> None:
    enforce_internal_observability_access(
        request=request,
        observability_internal_only=settings.observability_internal_only,
        trust_proxy_headers=settings.trust_proxy_headers,
        trusted_proxy_cidrs=settings.trusted_proxy_cidrs,
    )

    expected_token = (settings.operator_panel_token or "").strip()
    if not expected_token:
        raise HTTPException(status_code=503, detail="Painel de atendimento sem token configurado")

    provided_token = (
        request.headers.get("X-Operator-Token")
        or request.cookies.get("operator_panel_token")
        or request.query_params.get("token")
        or ""
    ).strip()
    if provided_token != expected_token:
        raise HTTPException(status_code=401, detail="Acesso não autorizado ao painel")


def create_operator_router(chat_service: ChatService, settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/operator", tags=["operator"])

    @router.get("", response_class=HTMLResponse)
    async def operator_index(request: Request):
        _require_operator_access(request, settings)
        query_token = (request.query_params.get("token") or "").strip()

        response = templates.TemplateResponse(
            request,
            "operator.html",
            {
                "service_name": "LavPop Atendimento",
                "default_mode": "aguardando_humano",
            },
        )
        if query_token and query_token == settings.operator_panel_token:
            response.set_cookie(
                "operator_panel_token",
                query_token,
                httponly=True,
                samesite="strict",
                secure=settings.app_env in {"prod", "production"},
            )
        return response

    @router.get("/api/conversations")
    async def list_conversations(request: Request, mode: str = "aguardando_humano", limit: int = 50):
        _require_operator_access(request, settings)
        return {
            "conversations": chat_service.list_operator_conversations(
                mode=mode,
                limit=limit,
            )
        }

    @router.get("/api/conversations/{phone}/messages")
    async def list_messages(request: Request, phone: str, limit: int = 100):
        _require_operator_access(request, settings)
        normalized_phone = normalize_phone(phone)
        return {
            "phone": normalized_phone,
            "messages": list(reversed(chat_service.list_operator_messages(normalized_phone, limit=limit))),
        }

    @router.post("/api/conversations/{phone}/claim")
    async def claim_conversation(request: Request, phone: str):
        _require_operator_access(request, settings)
        normalized_phone = normalize_phone(phone)
        chat_service.set_operator_conversation_mode(
            normalized_phone,
            "humano",
            "assumido_no_painel",
            status="ativo",
        )
        alert_sent = chat_service.notify_operator_handoff_start(normalized_phone)
        return {"status": "ok", "mode": "humano", "operator_alert_sent": alert_sent}

    @router.post("/api/conversations/{phone}/send")
    async def send_human_message(request: Request, phone: str, body: HumanMessageRequest):
        _require_operator_access(request, settings)
        sent = chat_service.send_human_message(normalize_phone(phone), body.text)
        return {"status": "sent" if sent else "send_failed", "sent": sent}

    @router.post("/api/conversations/{phone}/return-to-bot")
    async def return_to_bot(request: Request, phone: str):
        _require_operator_access(request, settings)
        normalized_phone = normalize_phone(phone)
        return chat_service.return_conversation_to_bot(normalized_phone)

    @router.post("/api/conversations/{phone}/close")
    async def close_conversation(request: Request, phone: str):
        _require_operator_access(request, settings)
        normalized_phone = normalize_phone(phone)
        chat_service.set_operator_conversation_mode(
            normalized_phone,
            "encerrado",
            "encerrado_no_painel",
            status="encerrado",
        )
        return {"status": "ok", "mode": "encerrado"}

    return router
