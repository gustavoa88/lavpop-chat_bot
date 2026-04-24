"""Regras de acesso por rede para endpoints operacionais."""

from __future__ import annotations

import ipaddress
import logging

from fastapi import HTTPException, Request

logger = logging.getLogger("meta_chatbot")


def resolve_request_ip(request: Request, trust_proxy_headers: bool, trusted_proxy_cidrs: tuple[str, ...]) -> str:
    """Resolve o IP de origem efetivo considerando proxies confiáveis."""
    client_host = (request.client.host.strip() if request.client and request.client.host else "")

    if trust_proxy_headers and is_trusted_proxy(client_host, trusted_proxy_cidrs):
        forwarded_for = (request.headers.get("x-forwarded-for") or "").strip()
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()

    return client_host


def is_internal_request(request_ip: str) -> bool:
    if request_ip in {"localhost", "testclient"}:
        return True

    try:
        parsed_ip = ipaddress.ip_address(request_ip)
    except ValueError:
        return False

    return parsed_ip.is_private or parsed_ip.is_loopback or parsed_ip.is_link_local


def is_trusted_proxy(request_ip: str, trusted_proxy_cidrs: tuple[str, ...]) -> bool:
    if request_ip in {"localhost", "testclient"}:
        return True

    try:
        parsed_ip = ipaddress.ip_address(request_ip)
    except ValueError:
        return False

    for cidr in trusted_proxy_cidrs:
        try:
            if parsed_ip in ipaddress.ip_network(cidr, strict=False):
                return True
        except ValueError:
            logger.warning("CIDR de proxy confiável inválido ignorado: %s", cidr)

    return False


def enforce_internal_observability_access(
    request: Request,
    observability_internal_only: bool,
    trust_proxy_headers: bool,
    trusted_proxy_cidrs: tuple[str, ...],
) -> None:
    if not observability_internal_only:
        return

    request_ip = resolve_request_ip(request, trust_proxy_headers, trusted_proxy_cidrs)
    if not is_internal_request(request_ip):
        raise HTTPException(status_code=403, detail="Endpoint operacional restrito a rede interna")
