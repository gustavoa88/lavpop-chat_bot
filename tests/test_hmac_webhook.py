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


def test_post_webhook_meta_deduplicates_message_id(monkeypatch):
    main_module = _load_main_module(monkeypatch, validate_signature=False, app_secret="")

    seen_events = set()
    answered_messages = []
    sent_messages = []

    def fake_try_register_webhook_event(event_key: str, payload_hash: str, source: str = "meta_webhook"):
        if event_key in seen_events:
            return False
        seen_events.add(event_key)
        return True

    def fake_answer_message(phone: str, contact_name: str, incoming_text: str):
        answered_messages.append((phone, contact_name, incoming_text))
        return "Resposta teste", "menu", None, "menu_inicial"

    def fake_send_meta_message(phone: str, answer: str):
        sent_messages.append((phone, answer))

    def fake_send_meta_menu_message(phone: str):
        return False

    main_module.db.try_register_webhook_event = fake_try_register_webhook_event
    main_module.chat_service.answer_message = fake_answer_message
    main_module.chat_service.send_meta_message = fake_send_meta_message
    main_module.chat_service.send_meta_menu_message = fake_send_meta_menu_message

    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "contacts": [{"profile": {"name": "Gustavo"}}],
                            "messages": [
                                {
                                    "id": "wamid.abc123",
                                    "from": "5511999999999",
                                    "timestamp": "1710000000",
                                    "type": "text",
                                    "text": {"body": "oi"},
                                },
                                {
                                    "id": "wamid.abc123",
                                    "from": "5511999999999",
                                    "timestamp": "1710000000",
                                    "type": "text",
                                    "text": {"body": "oi"},
                                },
                            ],
                        }
                    }
                ]
            }
        ]
    }

    with TestClient(main_module.app) as client:
        response = client.post("/webhook/meta", json=payload)

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert len(answered_messages) == 1
    assert len(sent_messages) == 1


def test_post_webhook_meta_interactive_list_reply_maps_to_menu_option(monkeypatch):
    main_module = _load_main_module(monkeypatch, validate_signature=False, app_secret="")

    answered_messages = []

    main_module.db.try_register_webhook_event = lambda **kwargs: True

    def fake_answer_message(phone: str, contact_name: str, incoming_text: str):
        answered_messages.append((phone, incoming_text))
        return "Resposta teste", "menu", None, "menu_opcao_1"

    main_module.chat_service.answer_message = fake_answer_message
    main_module.chat_service.send_meta_message = lambda phone, answer: None
    main_module.chat_service.send_meta_menu_message = lambda phone: True

    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "contacts": [{"profile": {"name": "Gustavo"}}],
                            "messages": [
                                {
                                    "id": "wamid.interactive123",
                                    "from": "5511999999999",
                                    "timestamp": "1710000100",
                                    "type": "interactive",
                                    "interactive": {
                                        "type": "list_reply",
                                        "list_reply": {
                                            "id": "menu_option_1",
                                            "title": "1) Horário de atendimento",
                                        },
                                    },
                                }
                            ],
                        }
                    }
                ]
            }
        ]
    }

    with TestClient(main_module.app) as client:
        response = client.post("/webhook/meta", json=payload)

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert answered_messages == [("5511999999999", "1")]


def test_post_webhook_meta_sends_interactive_menu_for_greeting(monkeypatch):
    main_module = _load_main_module(monkeypatch, validate_signature=False, app_secret="")

    menu_calls = []
    text_calls = []

    main_module.db.try_register_webhook_event = lambda **kwargs: True
    main_module.chat_service.answer_message = lambda phone, contact_name, incoming_text: (
        main_module.PROACTIVE_MENU_MESSAGE,
        "menu",
        None,
        "menu_inicial",
    )
    main_module.chat_service.send_meta_menu_message = lambda phone: menu_calls.append(phone) or True
    main_module.chat_service.send_meta_message = lambda phone, answer: text_calls.append((phone, answer))

    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "contacts": [{"profile": {"name": "Gustavo"}}],
                            "messages": [
                                {
                                    "id": "wamid.greeting123",
                                    "from": "5511999999999",
                                    "timestamp": "1710000200",
                                    "type": "text",
                                    "text": {"body": "oi"},
                                }
                            ],
                        }
                    }
                ]
            }
        ]
    }

    with TestClient(main_module.app) as client:
        response = client.post("/webhook/meta", json=payload)

    assert response.status_code == 200
    assert menu_calls == ["5511999999999"]
    assert text_calls == []


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


def test_health_db_returns_up_when_database_is_ready(monkeypatch):
    main_module = _load_main_module(monkeypatch, validate_signature=False, app_secret="")
    main_module.db.healthcheck = lambda: {"ready": True, "latency_ms": 1.23}

    with TestClient(main_module.app) as client:
        response = client.get("/health/db")

    assert response.status_code == 200
    assert response.json() == {
        "status": "up",
        "database": {"ready": True, "latency_ms": 1.23},
    }


def test_health_db_returns_503_when_database_is_unavailable(monkeypatch):
    main_module = _load_main_module(monkeypatch, validate_signature=False, app_secret="")
    main_module.db.healthcheck = lambda: {"ready": False, "latency_ms": 9.87, "error": "timeout"}

    with TestClient(main_module.app) as client:
        response = client.get("/health/db")

    assert response.status_code == 503
    assert response.json()["detail"]["status"] == "down"
    assert response.json()["detail"]["database"]["ready"] is False


def test_metrics_exposes_counters_and_database_status(monkeypatch):
    main_module = _load_main_module(monkeypatch, validate_signature=False, app_secret="")
    main_module.db.healthcheck = lambda: {"ready": True, "latency_ms": 2.5}

    with TestClient(main_module.app) as client:
        response = client.get("/metrics")

    assert response.status_code == 200
    assert "chatbot_webhook_requests_total" in response.text
    assert "chatbot_database_ready 1" in response.text


def test_metrics_returns_403_for_external_origin(monkeypatch):
    monkeypatch.setenv("TRUST_PROXY_HEADERS", "true")
    main_module = _load_main_module(monkeypatch, validate_signature=False, app_secret="")

    with TestClient(main_module.app) as client:
        response = client.get("/metrics", headers={"X-Forwarded-For": "8.8.8.8"})

    assert response.status_code == 403
    assert response.json()["detail"] == "Endpoint operacional restrito a rede interna"


def test_health_ready_returns_403_for_external_origin(monkeypatch):
    monkeypatch.setenv("TRUST_PROXY_HEADERS", "true")
    main_module = _load_main_module(monkeypatch, validate_signature=False, app_secret="")
    main_module.db.is_ready = lambda: True

    with TestClient(main_module.app) as client:
        response = client.get("/health/ready", headers={"X-Forwarded-For": "1.1.1.1"})

    assert response.status_code == 403
    assert response.json()["detail"] == "Endpoint operacional restrito a rede interna"


def test_metrics_ignores_x_forwarded_for_by_default(monkeypatch):
    main_module = _load_main_module(monkeypatch, validate_signature=False, app_secret="")
    main_module.db.healthcheck = lambda: {"ready": True, "latency_ms": 1.23}

    with TestClient(main_module.app) as client:
        response = client.get("/metrics", headers={"X-Forwarded-For": "8.8.8.8"})

    assert response.status_code == 200


def test_post_webhook_meta_interactive_button_reply_maps_to_menu_option(monkeypatch):
    main_module = _load_main_module(monkeypatch, validate_signature=False, app_secret="")

    answered_messages = []

    main_module.db.try_register_webhook_event = lambda **kwargs: True

    def fake_answer_message(phone: str, contact_name: str, incoming_text: str):
        answered_messages.append((phone, incoming_text))
        return "Resposta teste", "menu", None, "menu_opcao_2"

    main_module.chat_service.answer_message = fake_answer_message
    main_module.chat_service.send_meta_message = lambda phone, answer: None
    main_module.chat_service.send_meta_menu_message = lambda phone: True

    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "contacts": [{"profile": {"name": "Gustavo"}}],
                            "messages": [
                                {
                                    "id": "wamid.button123",
                                    "from": "5511999999999",
                                    "timestamp": "1710000111",
                                    "type": "interactive",
                                    "interactive": {
                                        "type": "button_reply",
                                        "button_reply": {
                                            "id": "menu_option_2",
                                            "title": "2) Preços",
                                        },
                                    },
                                }
                            ],
                        }
                    }
                ]
            }
        ]
    }

    with TestClient(main_module.app) as client:
        response = client.post("/webhook/meta", json=payload)

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert answered_messages == [("5511999999999", "2")]
