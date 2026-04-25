import importlib
import asyncio
from typing import Any

import httpx


DEFAULT_ENV = {
    "OPENAI_API_KEY": "",
    "OPENAI_MODEL": "gpt-4.1-mini",
    "META_VERIFY_TOKEN": "verify-token",
    "META_WHATSAPP_TOKEN": "",
    "META_PHONE_NUMBER_ID": "",
    "META_REQUIRE_APP_SECRET": "false",
    "DB_HOST": "127.0.0.1",
    "DB_PORT": "5432",
    "DB_NAME": "lavpop_chatbot",
    "DB_USER": "postgres",
    "DB_PASSWORD": "postgres",
    "DB_MIN_CONN": "1",
    "DB_MAX_CONN": "5",
    "DB_CONNECT_TIMEOUT": "3",
}


def _load_main_module(monkeypatch: Any):
    for key, value in DEFAULT_ENV.items():
        monkeypatch.setenv(key, value)

    monkeypatch.setenv("META_VALIDATE_SIGNATURE", "false")
    monkeypatch.setenv("META_APP_SECRET", "")

    import app.main as main_module

    main_module = importlib.reload(main_module)
    main_module.db.start = lambda: None
    main_module.db.stop = lambda: None
    return main_module


def _request(app, method: str, url: str, **kwargs) -> httpx.Response:
    async def send() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.request(method, url, **kwargs)

    return asyncio.run(send())


def test_get_webhook_meta_returns_challenge_when_token_is_valid(monkeypatch):
    main_module = _load_main_module(monkeypatch)

    response = _request(
        main_module.app,
        "GET",
        "/webhook/meta",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "verify-token",
            "hub.challenge": "challenge-123",
        },
    )

    assert response.status_code == 200
    assert response.text == "challenge-123"


def test_get_webhook_meta_returns_403_when_token_is_invalid(monkeypatch):
    main_module = _load_main_module(monkeypatch)

    response = _request(
        main_module.app,
        "GET",
        "/webhook/meta",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "token-invalido",
            "hub.challenge": "challenge-123",
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Falha na verificação do webhook"
