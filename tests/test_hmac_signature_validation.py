import hashlib
import hmac
from dataclasses import replace
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app import main


def _request_with_signature(signature: str):
    return SimpleNamespace(headers={"X-Hub-Signature-256": signature})


@pytest.fixture(autouse=True)
def reset_signature_warning_flag():
    main._meta_signature_secret_missing_logged = False
    yield
    main._meta_signature_secret_missing_logged = False


def _patch_settings(monkeypatch, *, validate_signature: bool, app_secret: str):
    patched_settings = replace(
        main.settings,
        meta_validate_signature=validate_signature,
        meta_app_secret=app_secret,
    )
    monkeypatch.setattr(main, "settings", patched_settings)


def test_validate_meta_signature_accepts_valid_signature(monkeypatch):
    _patch_settings(monkeypatch, validate_signature=True, app_secret="super-secret")

    body = b'{"entry": []}'
    valid_signature = "sha256=" + hmac.new(
        b"super-secret", body, hashlib.sha256
    ).hexdigest()

    main._validate_meta_signature(_request_with_signature(valid_signature), body)


def test_validate_meta_signature_rejects_invalid_signature(monkeypatch):
    _patch_settings(monkeypatch, validate_signature=True, app_secret="super-secret")

    body = b'{"entry": []}'
    request = _request_with_signature("sha256=assinatura-invalida")

    with pytest.raises(HTTPException) as exc_info:
        main._validate_meta_signature(request, body)

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Assinatura do webhook inválida"


def test_validate_meta_signature_compatibility_mode_allows_missing_secret(monkeypatch):
    _patch_settings(monkeypatch, validate_signature=True, app_secret="")

    body = b'{"entry": []}'
    request = _request_with_signature("")

    main._validate_meta_signature(request, body)
