from dataclasses import replace

import pytest

from app import main


def test_enforce_production_security_baseline_raises_when_meta_require_app_secret_is_false(monkeypatch):
    patched = replace(
        main.settings,
        app_env="production",
        meta_verify_token="verify-token",
        meta_whatsapp_token="whatsapp-token",
        meta_phone_number_id="phone-number-id",
        meta_app_secret="app-secret",
        meta_validate_signature=True,
        meta_require_app_secret=False,
        app_debug_log_mode=False,
    )
    monkeypatch.setattr(main, "settings", patched)

    with pytest.raises(RuntimeError, match="META_REQUIRE_APP_SECRET"):
        main._enforce_production_security_baseline()


def test_enforce_production_security_baseline_allows_non_production(monkeypatch):
    patched = replace(main.settings, app_env="dev", meta_require_app_secret=False)
    monkeypatch.setattr(main, "settings", patched)

    main._enforce_production_security_baseline()


def test_enforce_production_security_baseline_raises_when_meta_validate_signature_is_false(monkeypatch):
    patched = replace(
        main.settings,
        app_env="production",
        meta_verify_token="verify-token",
        meta_whatsapp_token="whatsapp-token",
        meta_phone_number_id="phone-number-id",
        meta_app_secret="app-secret",
        meta_validate_signature=False,
        meta_require_app_secret=True,
        app_debug_log_mode=False,
    )
    monkeypatch.setattr(main, "settings", patched)

    with pytest.raises(RuntimeError, match="META_VALIDATE_SIGNATURE"):
        main._enforce_production_security_baseline()


def test_enforce_production_security_baseline_raises_when_meta_app_secret_is_empty(monkeypatch):
    patched = replace(
        main.settings,
        app_env="production",
        meta_verify_token="verify-token",
        meta_whatsapp_token="whatsapp-token",
        meta_phone_number_id="phone-number-id",
        meta_app_secret="",
        meta_validate_signature=True,
        meta_require_app_secret=True,
        app_debug_log_mode=False,
    )
    monkeypatch.setattr(main, "settings", patched)

    with pytest.raises(RuntimeError, match="META_APP_SECRET"):
        main._enforce_production_security_baseline()


def test_enforce_production_security_baseline_raises_when_required_meta_config_is_empty(monkeypatch):
    patched = replace(
        main.settings,
        app_env="production",
        meta_verify_token="",
        meta_whatsapp_token="",
        meta_phone_number_id="",
        meta_app_secret="app-secret",
        meta_validate_signature=True,
        meta_require_app_secret=True,
        app_debug_log_mode=False,
    )
    monkeypatch.setattr(main, "settings", patched)

    with pytest.raises(RuntimeError) as exc_info:
        main._enforce_production_security_baseline()

    message = str(exc_info.value)
    assert "META_VERIFY_TOKEN" in message
    assert "META_WHATSAPP_TOKEN" in message
    assert "META_PHONE_NUMBER_ID" in message


def test_enforce_production_security_baseline_allows_strict_production_config(monkeypatch):
    patched = replace(
        main.settings,
        app_env="production",
        meta_verify_token="verify-token",
        meta_whatsapp_token="whatsapp-token",
        meta_phone_number_id="phone-number-id",
        meta_app_secret="app-secret",
        meta_validate_signature=True,
        meta_require_app_secret=True,
        app_debug_log_mode=False,
    )
    monkeypatch.setattr(main, "settings", patched)

    main._enforce_production_security_baseline()


def test_enforce_production_security_baseline_requires_operator_token_when_enabled(monkeypatch):
    patched = replace(
        main.settings,
        app_env="production",
        meta_verify_token="verify-token",
        meta_whatsapp_token="whatsapp-token",
        meta_phone_number_id="phone-number-id",
        meta_app_secret="app-secret",
        meta_validate_signature=True,
        meta_require_app_secret=True,
        app_debug_log_mode=False,
        operator_panel_enabled=True,
        operator_panel_token="",
    )
    monkeypatch.setattr(main, "settings", patched)

    with pytest.raises(RuntimeError, match="OPERATOR_PANEL_TOKEN"):
        main._enforce_production_security_baseline()
