"""Funções utilitárias para segurança e idempotência de webhook."""

from __future__ import annotations

import hashlib
import hmac
import json

from fastapi import HTTPException, Request


def validate_webhook_challenge(request: Request, expected_verify_token: str) -> str:
    mode = request.query_params.get("hub.mode")
    verify_token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    if mode == "subscribe" and verify_token == expected_verify_token and challenge:
        return challenge

    raise HTTPException(status_code=403, detail="Falha na verificação do webhook")


def validate_meta_signature(
    request: Request,
    body: bytes,
    *,
    validate_signature: bool,
    app_secret: str,
) -> None:
    if not validate_signature:
        return

    normalized_secret = (app_secret or "").strip()
    if not normalized_secret:
        return

    signature = (request.headers.get("X-Hub-Signature-256") or "").strip()
    if not signature.startswith("sha256="):
        raise HTTPException(status_code=403, detail="Assinatura do webhook ausente ou inválida")

    expected = "sha256=" + hmac.new(normalized_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise HTTPException(status_code=403, detail="Assinatura do webhook inválida")


def build_message_event_key(message_obj: dict, phone: str, incoming_text: str, msg_type: str) -> str:
    message_id = (message_obj.get("id") or "").strip()
    if message_id:
        return f"meta_msg_id:{message_id}"

    timestamp = (message_obj.get("timestamp") or "").strip()
    fingerprint = json.dumps(
        {
            "from": phone,
            "type": msg_type,
            "text": incoming_text,
            "timestamp": timestamp,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    digest = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()
    return f"meta_msg_fallback:{digest}"
