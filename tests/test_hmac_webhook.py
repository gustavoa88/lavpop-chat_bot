import hashlib
import hmac
import importlib
import json
import asyncio
from dataclasses import replace
from typing import Any

import httpx
import pytest

from app.conversation_router import HANDOFF_ACTION, REGISTER_ONLY_ACTION, RouteDecision


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
    "APP_ENV": "dev",
    "APP_DEBUG_LOG_MODE": "false",
    "WEBHOOK_RATE_LIMIT_PER_MINUTE": "120",
}


def _load_main_module(monkeypatch: Any, *, validate_signature: bool, app_secret: str, app_env: str = "dev"):
    for key, value in DEFAULT_ENV.items():
        monkeypatch.setenv(key, value)

    monkeypatch.setenv("APP_ENV", app_env)
    monkeypatch.setenv("META_VALIDATE_SIGNATURE", "true" if validate_signature else "false")
    monkeypatch.setenv("META_APP_SECRET", app_secret)

    import app.main as main_module

    main_module = importlib.reload(main_module)
    main_module.db.start = lambda: None
    main_module.db.stop = lambda: None

    async def run_inline(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    main_module.run_in_threadpool = run_inline
    return main_module


def _make_signature(secret: str, body: bytes) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _request(app, method: str, url: str, **kwargs) -> httpx.Response:
    async def send() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.request(method, url, **kwargs)

    return asyncio.run(send())


def test_post_webhook_meta_accepts_valid_hmac_signature(monkeypatch):
    main_module = _load_main_module(monkeypatch, validate_signature=True, app_secret="topsecret")

    payload = {"entry": []}
    raw_body = json.dumps(payload).encode("utf-8")
    headers = {"X-Hub-Signature-256": _make_signature("topsecret", raw_body)}

    response = _request(
        main_module.app,
        "POST",
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

    response = _request(
        main_module.app,
        "POST",
        "/webhook/meta",
        content=raw_body,
        headers=headers,
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Assinatura do webhook inválida"

    metrics_response = _request(main_module.app, "GET", "/metrics")
    assert "chatbot_webhook_signature_failures_total 1" in metrics_response.text
    assert 'chatbot_message_processing_errors_by_type_total{type="signature_failure"} 1' in metrics_response.text


def test_post_webhook_meta_rejects_invalid_json_and_tracks_error_type(monkeypatch):
    main_module = _load_main_module(monkeypatch, validate_signature=False, app_secret="")

    response = _request(
        main_module.app,
        "POST",
        "/webhook/meta",
        content=b"{invalid",
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Payload JSON inválido"

    metrics_response = _request(main_module.app, "GET", "/metrics")
    assert 'chatbot_message_processing_errors_by_type_total{type="invalid_json"} 1' in metrics_response.text


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

    response = _request(main_module.app, "POST", "/webhook/meta", json=payload)

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert len(answered_messages) == 1
    assert len(sent_messages) == 1


def test_post_webhook_meta_redacts_message_preview_in_production_logs(monkeypatch, caplog):
    main_module = _load_main_module(monkeypatch, validate_signature=False, app_secret="", app_env="production")

    main_module.db.try_register_webhook_event = lambda **kwargs: True
    main_module.chat_service.answer_message = lambda *args, **kwargs: ("ok", "menu", None, "menu_inicial")
    main_module.chat_service.send_meta_message = lambda *args, **kwargs: True
    main_module.chat_service.send_meta_menu_message = lambda *args, **kwargs: True

    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "contacts": [{"profile": {"name": "Gustavo"}}],
                            "messages": [
                                {
                                    "id": "wamid.redacted123",
                                    "from": "5511912345678",
                                    "timestamp": "1710000000",
                                    "type": "text",
                                    "text": {"body": "meu telefone é 5511912345678"},
                                }
                            ],
                        }
                    }
                ]
            }
        ]
    }
    caplog.set_level("INFO", logger="meta_chatbot")
    response = _request(main_module.app, "POST", "/webhook/meta", json=payload)

    assert response.status_code == 200
    joined_logs = "\n".join(record.getMessage() for record in caplog.records)
    assert "preview=[redacted]" in joined_logs
    assert "meu telefone é 5511912345678" not in joined_logs
    assert "phone=5511912345678" not in joined_logs


def test_post_webhook_meta_notifies_operator_on_handoff(monkeypatch):
    main_module = _load_main_module(monkeypatch, validate_signature=False, app_secret="")

    alerts = []
    main_module.db.try_register_webhook_event = lambda **kwargs: True
    main_module.chat_service.notify_operator_handoff_start = lambda phone: alerts.append(phone) or True
    main_module.chat_service.send_meta_message = lambda *args, **kwargs: True
    main_module.chat_service.send_meta_menu_message = lambda *args, **kwargs: True
    main_module.conversation_router.decide = lambda *args, **kwargs: RouteDecision(
        mode="humano",
        action=HANDOFF_ACTION,
        answer="Vou te encaminhar para atendimento humano.",
        reason="pedido_atendimento_humano",
    )

    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "contacts": [{"profile": {"name": "Gustavo"}}],
                            "messages": [
                                {
                                    "id": "wamid.handoff123",
                                    "from": "5511941878601",
                                    "timestamp": "1710000000",
                                    "type": "text",
                                    "text": {"body": "quero falar com atendente"},
                                }
                            ],
                        }
                    }
                ]
            }
        ]
    }

    response = _request(main_module.app, "POST", "/webhook/meta", json=payload)

    assert response.status_code == 200
    assert alerts == ["5511941878601"]


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

    response = _request(main_module.app, "POST", "/webhook/meta", json=payload)

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

    response = _request(main_module.app, "POST", "/webhook/meta", json=payload)

    assert response.status_code == 200
    assert menu_calls == ["5511999999999"]
    assert text_calls == []


def test_post_webhook_meta_compatibility_mode_without_app_secret(monkeypatch):
    main_module = _load_main_module(monkeypatch, validate_signature=True, app_secret="")

    payload = {"entry": []}
    raw_body = json.dumps(payload).encode("utf-8")

    response = _request(main_module.app, "POST", "/webhook/meta", content=raw_body)

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

    async def start_app():
        async with main_module.lifespan(main_module.app):
            pass

    with pytest.raises(RuntimeError, match="META_APP_SECRET é obrigatório"):
        asyncio.run(start_app())


def test_startup_fails_in_production_with_debug_log_mode(monkeypatch):
    for key, value in DEFAULT_ENV.items():
        monkeypatch.setenv(key, value)

    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("APP_DEBUG_LOG_MODE", "true")
    monkeypatch.setenv("META_VALIDATE_SIGNATURE", "true")
    monkeypatch.setenv("META_REQUIRE_APP_SECRET", "true")
    monkeypatch.setenv("META_APP_SECRET", "topsecret")
    monkeypatch.setenv("META_WHATSAPP_TOKEN", "whatsapp-token")
    monkeypatch.setenv("META_PHONE_NUMBER_ID", "phone-number-id")

    import app.main as main_module

    main_module = importlib.reload(main_module)
    main_module.db.start = lambda: None
    main_module.db.stop = lambda: None

    async def start_app():
        async with main_module.lifespan(main_module.app):
            pass

    with pytest.raises(RuntimeError, match="APP_DEBUG_LOG_MODE deve ser false"):
        asyncio.run(start_app())


def test_production_disables_interactive_api_docs(monkeypatch):
    for key, value in DEFAULT_ENV.items():
        monkeypatch.setenv(key, value)

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("APP_DEBUG_LOG_MODE", "false")
    monkeypatch.setenv("META_VALIDATE_SIGNATURE", "true")
    monkeypatch.setenv("META_REQUIRE_APP_SECRET", "true")
    monkeypatch.setenv("META_APP_SECRET", "topsecret")
    monkeypatch.setenv("META_WHATSAPP_TOKEN", "whatsapp-token")
    monkeypatch.setenv("META_PHONE_NUMBER_ID", "phone-number-id")

    import app.main as main_module

    main_module = importlib.reload(main_module)

    assert _request(main_module.app, "GET", "/docs").status_code == 404
    assert _request(main_module.app, "GET", "/redoc").status_code == 404
    assert _request(main_module.app, "GET", "/openapi.json").status_code == 404


def test_post_webhook_meta_rate_limits_when_limit_is_exceeded(monkeypatch):
    main_module = _load_main_module(monkeypatch, validate_signature=False, app_secret="")
    patched_settings = replace(main_module.settings, webhook_rate_limit_per_minute=1)
    monkeypatch.setattr(main_module, "settings", patched_settings)

    payload = {"entry": []}
    first = _request(main_module.app, "POST", "/webhook/meta", json=payload)
    second = _request(main_module.app, "POST", "/webhook/meta", json=payload)

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()["detail"] == "Rate limit excedido"


def test_health_live_returns_alive(monkeypatch):
    main_module = _load_main_module(monkeypatch, validate_signature=False, app_secret="")
    main_module.db.is_ready = lambda: True

    response = _request(main_module.app, "GET", "/health/live")

    assert response.status_code == 200
    assert response.json()["status"] == "alive"


def test_health_ready_returns_ok_when_database_is_ready(monkeypatch):
    main_module = _load_main_module(monkeypatch, validate_signature=False, app_secret="")
    main_module.db.is_ready = lambda: True

    response = _request(main_module.app, "GET", "/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "dependencies": {"database": "ok"}}


def test_health_ready_returns_503_when_database_is_unavailable(monkeypatch):
    main_module = _load_main_module(monkeypatch, validate_signature=False, app_secret="")
    main_module.db.is_ready = lambda: False

    response = _request(main_module.app, "GET", "/health/ready")

    assert response.status_code == 503
    assert response.json()["detail"] == "Banco de dados indisponível"


def test_health_db_returns_up_when_database_is_ready(monkeypatch):
    main_module = _load_main_module(monkeypatch, validate_signature=False, app_secret="")
    main_module.db.healthcheck = lambda: {"ready": True, "latency_ms": 1.23}

    response = _request(main_module.app, "GET", "/health/db")

    assert response.status_code == 200
    assert response.json() == {
        "status": "up",
        "database": {"ready": True, "latency_ms": 1.23},
    }


def test_health_db_returns_503_when_database_is_unavailable(monkeypatch):
    main_module = _load_main_module(monkeypatch, validate_signature=False, app_secret="")
    main_module.db.healthcheck = lambda: {"ready": False, "latency_ms": 9.87, "error": "timeout"}

    response = _request(main_module.app, "GET", "/health/db")

    assert response.status_code == 503
    assert response.json()["detail"]["status"] == "down"
    assert response.json()["detail"]["database"]["ready"] is False


def test_metrics_exposes_counters_and_database_status(monkeypatch):
    main_module = _load_main_module(monkeypatch, validate_signature=False, app_secret="")
    main_module.db.healthcheck = lambda: {"ready": True, "latency_ms": 2.5}

    response = _request(main_module.app, "GET", "/metrics")

    assert response.status_code == 200
    assert "chatbot_webhook_requests_total" in response.text
    assert "chatbot_webhook_processing_duration_seconds_count" in response.text
    assert "chatbot_database_ready 1" in response.text


def test_metrics_returns_403_for_external_origin(monkeypatch):
    monkeypatch.setenv("TRUST_PROXY_HEADERS", "true")
    main_module = _load_main_module(monkeypatch, validate_signature=False, app_secret="")

    response = _request(main_module.app, "GET", "/metrics", headers={"X-Forwarded-For": "8.8.8.8"})

    assert response.status_code == 403
    assert response.json()["detail"] == "Endpoint operacional restrito a rede interna"


def test_health_ready_returns_403_for_external_origin(monkeypatch):
    monkeypatch.setenv("TRUST_PROXY_HEADERS", "true")
    main_module = _load_main_module(monkeypatch, validate_signature=False, app_secret="")
    main_module.db.is_ready = lambda: True

    response = _request(main_module.app, "GET", "/health/ready", headers={"X-Forwarded-For": "1.1.1.1"})

    assert response.status_code == 403
    assert response.json()["detail"] == "Endpoint operacional restrito a rede interna"


def test_metrics_ignores_x_forwarded_for_by_default(monkeypatch):
    main_module = _load_main_module(monkeypatch, validate_signature=False, app_secret="")
    main_module.db.healthcheck = lambda: {"ready": True, "latency_ms": 1.23}

    response = _request(main_module.app, "GET", "/metrics", headers={"X-Forwarded-For": "8.8.8.8"})

    assert response.status_code == 200


def test_post_webhook_meta_interactive_button_reply_maps_to_menu_option(monkeypatch):
    main_module = _load_main_module(monkeypatch, validate_signature=False, app_secret="")

    answered_messages = []

    main_module.db.try_register_webhook_event = lambda **kwargs: True

    def fake_answer_message(phone: str, contact_name: str, incoming_text: str):
        answered_messages.append((phone, incoming_text))
        return "Resposta teste", "menu", None, "menu_opcao_2"

    main_module.chat_service.answer_message = fake_answer_message
    main_module.chat_service.send_meta_message = lambda phone, answer: True
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

    response = _request(main_module.app, "POST", "/webhook/meta", json=payload)
    metrics_response = _request(main_module.app, "GET", "/metrics")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert answered_messages == [("5511999999999", "2")]
    assert 'chatbot_responses_by_source_total{source="menu"} 1' in metrics_response.text


def test_post_webhook_meta_register_only_action_increments_recorded_metric(monkeypatch):
    main_module = _load_main_module(monkeypatch, validate_signature=False, app_secret="")

    main_module.db.try_register_webhook_event = lambda **kwargs: True
    main_module.chat_service.send_meta_message = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("Não deve enviar mensagem quando ação for apenas registrar")
    )
    main_module.chat_service.send_meta_menu_message = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("Não deve enviar menu quando ação for apenas registrar")
    )
    main_module.conversation_router.decide = lambda *_args, **_kwargs: RouteDecision(
        action=REGISTER_ONLY_ACTION,
        mode="bot",
        reason="teste_registro_sem_resposta",
    )

    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "contacts": [{"profile": {"name": "Cliente"}}],
                            "messages": [
                                {
                                    "id": "wamid.register_only",
                                    "from": "5511999999999",
                                    "timestamp": "1710000222",
                                    "type": "text",
                                    "text": {"body": "apenas registrar"},
                                }
                            ],
                        }
                    }
                ]
            }
        ]
    }

    webhook_response = _request(main_module.app, "POST", "/webhook/meta", json=payload)
    metrics_response = _request(main_module.app, "GET", "/metrics")

    assert webhook_response.status_code == 200
    assert webhook_response.json() == {"status": "ok"}
    assert metrics_response.status_code == 200
    assert "chatbot_messages_recorded_total 1" in metrics_response.text
    assert "chatbot_message_processing_errors_total 0" in metrics_response.text
