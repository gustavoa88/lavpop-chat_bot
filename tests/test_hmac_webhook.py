import hashlib
import hmac
import importlib
import json
from typing import Any

import pytest
from fastapi.testclient import TestClient


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


def _load_main_module(monkeypatch: Any, *, validate_signature: bool, app_secret: str):
    for key, value in DEFAULT_ENV.items():
        monkeypatch.setenv(key, value)

    monkeypatch.setenv("META_VALIDATE_SIGNATURE", "true" if validate_signature else "false")
    monkeypatch.setenv("META_APP_SECRET", app_secret)

    import app.main as main_module

    main_module = importlib.reload(main_module)
    main_module.db.start = lambda: None
    main_module.db.stop = lambda: None
    return main_module


def _make_signature(secret: str, body: bytes) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def test_post_webhook_meta_accepts_valid_hmac_signature(monkeypatch):
    main_module = _load_main_module(monkeypatch, validate_signature=True, app_secret="topsecret")

    payload = {"entry": []}
    raw_body = json.dumps(payload).encode("utf-8")
    headers = {"X-Hub-Signature-256": _make_signature("topsecret", raw_body)}

    with TestClient(main_module.app) as client:
        response = client.post(
            "/webhook/meta",
            content=raw_body,
            headers=headers,
        )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_post_webhook_meta_rejects_invalid_hmac_signature(monkeypatch):
    main_module = _load_main_module(monkeypatch, validate_signature=True, app_secret="topsecret")

    payload = {"entry": []}
    raw_body = json.dumps(payload).encode("utf-8")
    headers = {"X-Hub-Signature-256": "sha256=invalidsignature"}

    with TestClient(main_module.app) as client:
        response = client.post(
            "/webhook/meta",
            content=raw_body,
            headers=headers,
        )

    assert response.status_code == 403
    assert response.json()["detail"] == "Assinatura do webhook inválida"


def test_post_webhook_meta_compatibility_mode_without_app_secret(monkeypatch):
    main_module = _load_main_module(monkeypatch, validate_signature=True, app_secret="")

    payload = {"entry": []}
    raw_body = json.dumps(payload).encode("utf-8")

    with TestClient(main_module.app) as client:
        response = client.post(
            "/webhook/meta",
            content=raw_body,
        )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_startup_fails_in_strict_mode_without_app_secret(monkeypatch):
    for key, value in DEFAULT_ENV.items():
        monkeypatch.setenv(key, value)

    monkeypatch.setenv("META_VALIDATE_SIGNATURE", "true")
    monkeypatch.setenv("META_REQUIRE_APP_SECRET", "true")
    monkeypatch.setenv("META_APP_SECRET", "")

    import app.main as main_module

    main_module = importlib.reload(main_module)
    main_module.db.start = lambda: None
    main_module.db.stop = lambda: None

    with pytest.raises(RuntimeError, match="META_APP_SECRET é obrigatório"):
        with TestClient(main_module.app):
            pass


def test_health_live_returns_alive(monkeypatch):
    main_module = _load_main_module(monkeypatch, validate_signature=False, app_secret="")
    main_module.db.is_ready = lambda: True

    with TestClient(main_module.app) as client:
        response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json()["status"] == "alive"


def test_health_ready_returns_ok_when_database_is_ready(monkeypatch):
    main_module = _load_main_module(monkeypatch, validate_signature=False, app_secret="")
    main_module.db.is_ready = lambda: True

    with TestClient(main_module.app) as client:
        response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "dependencies": {"database": "ok"}}


def test_health_ready_returns_503_when_database_is_unavailable(monkeypatch):
    main_module = _load_main_module(monkeypatch, validate_signature=False, app_secret="")
    main_module.db.is_ready = lambda: False

    with TestClient(main_module.app) as client:
        response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["detail"] == "Banco de dados indisponível"
