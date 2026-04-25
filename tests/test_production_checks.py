from __future__ import annotations

from dataclasses import dataclass
from urllib.error import URLError

import pytest

import app.production_checks as production_checks
from app.production_checks import DEFAULT_SMOKE_PATHS, build_target_url, run_production_smoke_checks


@dataclass
class _FakeResponse:
    status_code: int
    body: bytes

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def getcode(self):
        return self.status_code

    def read(self):
        return self.body


def test_build_target_url_normalizes_base_and_path():
    assert build_target_url("https://example.com/", "health/live") == "https://example.com/health/live"


def test_run_production_smoke_checks_succeeds_against_expected_endpoints(monkeypatch):
    responses = {
        "http://example.com/": _FakeResponse(200, b"ok"),
        "http://example.com/health/live": _FakeResponse(200, b"alive"),
        "http://example.com/health/ready": _FakeResponse(200, b"ready"),
        "http://example.com/health/db": _FakeResponse(200, b"db"),
    }

    def fake_urlopen(request, timeout=0):
        return responses[request.full_url]

    monkeypatch.setattr(production_checks, "urlopen", fake_urlopen)

    results = run_production_smoke_checks("http://example.com/")

    assert [result.path for result in results] == list(DEFAULT_SMOKE_PATHS)
    assert all(result.ok for result in results)


def test_run_production_smoke_checks_raises_when_endpoint_fails(monkeypatch):
    responses = {
        "http://example.com/": _FakeResponse(200, b"ok"),
        "http://example.com/health/live": _FakeResponse(200, b"alive"),
        "http://example.com/health/ready": _FakeResponse(503, b"down"),
        "http://example.com/health/db": _FakeResponse(200, b"db"),
    }

    def fake_urlopen(request, timeout=0):
        return responses[request.full_url]

    monkeypatch.setattr(production_checks, "urlopen", fake_urlopen)

    with pytest.raises(RuntimeError, match=r"/health/ready"):
        run_production_smoke_checks("http://example.com/")


def test_run_production_smoke_checks_raises_when_connection_fails(monkeypatch):
    def fake_urlopen(request, timeout=0):
        raise URLError("connection refused")

    monkeypatch.setattr(production_checks, "urlopen", fake_urlopen)

    with pytest.raises(RuntimeError, match=r"erro ao conectar"):
        run_production_smoke_checks("http://example.com/")
