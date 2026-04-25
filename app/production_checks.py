from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_SMOKE_PATHS: tuple[str, ...] = (
    "/",
    "/health/live",
    "/health/ready",
    "/health/db",
)


@dataclass(frozen=True)
class SmokeTestResult:
    path: str
    url: str
    status_code: int
    expected_status_code: int
    ok: bool
    body_preview: str


def normalize_base_url(base_url: str) -> str:
    normalized = (base_url or "").strip().rstrip("/")
    if not normalized:
        raise ValueError("Base URL de produção não informada.")
    if not normalized.startswith(("http://", "https://")):
        raise ValueError("Base URL de produção deve começar com http:// ou https://.")
    return normalized


def build_target_url(base_url: str, path: str) -> str:
    normalized_base = normalize_base_url(base_url)
    normalized_path = path.strip()
    if not normalized_path:
        raise ValueError("Caminho de smoke test vazio.")
    if not normalized_path.startswith("/"):
        normalized_path = "/" + normalized_path
    return f"{normalized_base}{normalized_path}"


def _body_preview(body: bytes, limit: int = 160) -> str:
    if not body:
        return ""
    preview = body.decode("utf-8", errors="replace").strip().replace("\n", " ")
    if len(preview) <= limit:
        return preview
    return preview[: limit - 3] + "..."


def run_production_smoke_checks(
    base_url: str,
    *,
    timeout_seconds: float = 5.0,
    paths: Sequence[str] = DEFAULT_SMOKE_PATHS,
    expected_status_codes: Mapping[str, int] | None = None,
    headers: Mapping[str, str] | None = None,
) -> list[SmokeTestResult]:
    normalized_base = normalize_base_url(base_url)
    expected = dict(expected_status_codes or {})
    request_headers = dict(headers or {})
    results: list[SmokeTestResult] = []
    failures: list[str] = []

    for path in paths:
        url = build_target_url(normalized_base, path)
        expected_status = expected.get(path, 200)
        request = Request(url, headers=request_headers, method="GET")

        body = b""
        status_code = 0
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                status_code = int(response.getcode() or 0)
                body = response.read()
        except HTTPError as exc:
            status_code = int(exc.code or 0)
            body = exc.read() or b""
        except URLError as exc:
            failures.append(f"{path}: erro ao conectar em {url} ({exc.reason})")
            results.append(
                SmokeTestResult(
                    path=path,
                    url=url,
                    status_code=0,
                    expected_status_code=expected_status,
                    ok=False,
                    body_preview="",
                )
            )
            continue

        ok = status_code == expected_status
        if not ok:
            failures.append(f"{path}: status {status_code} esperado {expected_status}")

        results.append(
            SmokeTestResult(
                path=path,
                url=url,
                status_code=status_code,
                expected_status_code=expected_status,
                ok=ok,
                body_preview=_body_preview(body),
            )
        )

    if failures:
        summary = "; ".join(failures)
        raise RuntimeError(f"Smoke test de produção falhou: {summary}")

    return results
