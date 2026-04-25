"""Diagnóstico sequencial de DNS, borda e serviço da aplicação."""

from __future__ import annotations

import socket
import subprocess
from dataclasses import dataclass
from typing import Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class StepResult:
    name: str
    ok: bool
    detail: str


def resolve_domain(domain: str) -> list[str]:
    addresses = {
        info[4][0]
        for info in socket.getaddrinfo(domain, None, proto=socket.IPPROTO_TCP)
    }
    return sorted(addresses)


def check_http(url: str, timeout_seconds: float = 5.0) -> tuple[int, str]:
    request = Request(url, method="GET")
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            body = response.read(256)
            preview = body.decode("utf-8", errors="replace").strip().replace("\n", " ")
            return int(response.getcode() or 0), preview
    except HTTPError as exc:
        body = exc.read(256) if hasattr(exc, "read") else b""
        preview = body.decode("utf-8", errors="replace").strip().replace("\n", " ")
        return int(exc.code or 0), preview or (exc.reason if exc.reason else "")


def run_remote_command(
    ssh_target: str,
    command: str,
    *,
    ssh_port: int = 22,
    timeout_seconds: int = 20,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=10",
            "-p",
            str(ssh_port),
            ssh_target,
            command,
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )


def sequence_check(
    domain: str,
    *,
    public_url: str | None = None,
    ssh_target: str | None = None,
    ssh_port: int = 22,
    service_name: str = "lavpop-chatbot",
    app_port: int = 8000,
    timeout_seconds: float = 5.0,
) -> list[StepResult]:
    results: list[StepResult] = []

    try:
        addresses = resolve_domain(domain)
        results.append(StepResult("DNS", True, ", ".join(addresses)))
    except Exception as exc:
        results.append(StepResult("DNS", False, str(exc)))
        return results

    target = (public_url or f"http://{domain}").rstrip("/")
    for path in ("", "/health/live", "/health/ready", "/health/db"):
        url = f"{target}{path}"
        try:
            status_code, preview = check_http(url, timeout_seconds=timeout_seconds)
            ok = 200 <= status_code < 400
            detail = f"{status_code} {preview}".strip()
            results.append(StepResult(f"HTTP {path or '/'}", ok, detail))
        except URLError as exc:
            results.append(StepResult(f"HTTP {path or '/'}", False, str(exc)))

    if not ssh_target:
        return results

    remote_commands: Sequence[tuple[str, str]] = (
        ("Firewall", "sudo ufw status verbose"),
        (
            "Nginx config",
            "sudo nginx -t",
        ),
        (
            "Nginx ports",
            "sudo ss -ltnp | egrep ':(80|443)\\b|:8000\\b' || true",
        ),
        (
            "Nginx status",
            "sudo systemctl status nginx --no-pager",
        ),
        (
            "Service status",
            f"sudo systemctl status {service_name} --no-pager",
        ),
        (
            "App localhost",
            f"curl -I --max-time {int(timeout_seconds)} http://127.0.0.1:{app_port}/",
        ),
        (
            "Health live",
            f"curl -I --max-time {int(timeout_seconds)} http://127.0.0.1:{app_port}/health/live",
        ),
        (
            "Health ready",
            f"curl -I --max-time {int(timeout_seconds)} http://127.0.0.1:{app_port}/health/ready",
        ),
        (
            "Health db",
            f"curl -I --max-time {int(timeout_seconds)} http://127.0.0.1:{app_port}/health/db",
        ),
    )

    for step_name, command in remote_commands:
        try:
            completed = run_remote_command(ssh_target, command, ssh_port=ssh_port)
            stdout = completed.stdout.strip()
            stderr = completed.stderr.strip()
            detail = stdout or stderr or f"exit={completed.returncode}"
            results.append(StepResult(step_name, completed.returncode == 0, detail))
        except Exception as exc:
            results.append(StepResult(step_name, False, str(exc)))

    return results
