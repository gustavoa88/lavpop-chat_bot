from __future__ import annotations

import asyncio
import importlib
from typing import Any

import httpx


DEFAULT_ENV = {
    "OPENAI_API_KEY": "",
    "OPENAI_MODEL": "gpt-4.1-mini",
    "META_VERIFY_TOKEN": "verify-token",
    "META_WHATSAPP_TOKEN": "",
    "META_PHONE_NUMBER_ID": "",
    "META_APP_SECRET": "",
    "META_VALIDATE_SIGNATURE": "false",
    "META_REQUIRE_APP_SECRET": "false",
    "DB_HOST": "127.0.0.1",
    "DB_PORT": "5432",
    "DB_NAME": "lavpop_chatbot",
    "DB_USER": "postgres",
    "DB_PASSWORD": "postgres",
    "DB_MIN_CONN": "1",
    "DB_MAX_CONN": "5",
    "DB_CONNECT_TIMEOUT": "3",
    "APP_ENV": "dev",
    "APP_DEBUG_LOG_MODE": "false",
    "WEBHOOK_RATE_LIMIT_PER_MINUTE": "120",
    "OBSERVABILITY_INTERNAL_ONLY": "true",
    "OPERATOR_PANEL_ENABLED": "true",
    "OPERATOR_PANEL_TOKEN": "panel-token",
}


def _load_main_module(monkeypatch: Any):
    for key, value in DEFAULT_ENV.items():
        monkeypatch.setenv(key, value)

    import app.main as main_module

    return importlib.reload(main_module)


def _request(app, method: str, url: str, **kwargs) -> httpx.Response:
    async def send() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.request(method, url, **kwargs)

    return asyncio.run(send())


def test_operator_panel_requires_token(monkeypatch):
    main_module = _load_main_module(monkeypatch)

    response = _request(main_module.app, "GET", "/operator")

    assert response.status_code == 401


def test_operator_panel_renders_with_valid_token(monkeypatch):
    main_module = _load_main_module(monkeypatch)

    response = _request(main_module.app, "GET", "/operator?token=panel-token")

    assert response.status_code == 200
    assert "Atendimento" in response.text
    assert "operator_panel_token=" in response.headers["set-cookie"]


def test_operator_api_lists_conversations(monkeypatch):
    main_module = _load_main_module(monkeypatch)
    main_module.chat_service.list_operator_conversations = lambda mode, limit: [
        {
            "telefone": "5511999999999",
            "nome": "Cliente Teste",
            "modo_conversa": mode,
            "ultima_mensagem": "preciso de ajuda",
        }
    ]

    response = _request(
        main_module.app,
        "GET",
        "/operator/api/conversations?mode=aguardando_humano",
        headers={"X-Operator-Token": "panel-token"},
    )

    assert response.status_code == 200
    assert response.json()["conversations"][0]["telefone"] == "5511999999999"


def test_operator_api_claim_send_return_and_close(monkeypatch):
    main_module = _load_main_module(monkeypatch)
    calls = []

    def fake_set_mode(phone: str, mode: str, reason: str, status: str = "ativo"):
        calls.append(("mode", phone, mode, reason, status))

    def fake_send(phone: str, text: str):
        calls.append(("send", phone, text))
        return True

    def fake_return_to_bot(phone: str):
        calls.append(("return", phone))
        return {"status": "ok", "mode": "bot", "transition_sent": True, "menu_sent": True}

    main_module.chat_service.set_operator_conversation_mode = fake_set_mode
    main_module.chat_service.send_human_message = fake_send
    main_module.chat_service.return_conversation_to_bot = fake_return_to_bot
    headers = {"X-Operator-Token": "panel-token"}

    claim = _request(
        main_module.app,
        "POST",
        "/operator/api/conversations/5511999999999/claim",
        headers=headers,
    )
    send = _request(
        main_module.app,
        "POST",
        "/operator/api/conversations/whatsapp:+5511999999999/send",
        headers=headers,
        json={"text": "Olá, vou te ajudar."},
    )
    returned = _request(
        main_module.app,
        "POST",
        "/operator/api/conversations/5511999999999/return-to-bot",
        headers=headers,
    )
    closed = _request(
        main_module.app,
        "POST",
        "/operator/api/conversations/5511999999999/close",
        headers=headers,
    )

    assert claim.json()["mode"] == "humano"
    assert send.json()["sent"] is True
    assert returned.json()["mode"] == "bot"
    assert returned.json()["menu_sent"] is True
    assert closed.json()["mode"] == "encerrado"
    assert ("send", "5511999999999", "Olá, vou te ajudar.") in calls
    assert ("return", "5511999999999") in calls
