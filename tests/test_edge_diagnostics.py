from __future__ import annotations

import subprocess

import app.edge_diagnostics as edge_diagnostics


def test_resolve_domain_collects_addresses(monkeypatch):
    monkeypatch.setattr(
        edge_diagnostics.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (None, None, None, None, ("203.0.113.10", 0)),
            (None, None, None, None, ("2001:db8::1", 0)),
            (None, None, None, None, ("203.0.113.10", 0)),
        ],
    )

    assert edge_diagnostics.resolve_domain("example.com") == ["2001:db8::1", "203.0.113.10"]


def test_check_http_returns_status_and_preview(monkeypatch):
    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def getcode(self):
            return 200

        def read(self, size=-1):
            return b"ok"

    monkeypatch.setattr(edge_diagnostics, "urlopen", lambda *args, **kwargs: _Response())

    status_code, preview = edge_diagnostics.check_http("http://example.com")
    assert status_code == 200
    assert preview == "ok"


def test_run_remote_command_builds_ssh_invocation(monkeypatch):
    captured = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="done\n", stderr="")

    monkeypatch.setattr(edge_diagnostics.subprocess, "run", fake_run)

    completed = edge_diagnostics.run_remote_command("ops@example.com", "sudo nginx -t", ssh_port=2222)

    assert completed.returncode == 0
    assert captured["args"] == [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=10",
        "-p",
        "2222",
        "ops@example.com",
        "sudo nginx -t",
    ]
    assert captured["kwargs"]["capture_output"] is True


def test_sequence_check_reports_dns_failure_and_stops(monkeypatch):
    monkeypatch.setattr(edge_diagnostics, "resolve_domain", lambda domain: (_ for _ in ()).throw(OSError("no dns")))

    results = edge_diagnostics.sequence_check("example.com")
    assert results[0].name == "DNS"
    assert results[0].ok is False


def test_sequence_check_collects_remote_steps(monkeypatch):
    monkeypatch.setattr(edge_diagnostics, "resolve_domain", lambda domain: ["203.0.113.10"])
    monkeypatch.setattr(
        edge_diagnostics,
        "check_http",
        lambda url, timeout_seconds=5.0: (200, "ok"),
    )
    monkeypatch.setattr(
        edge_diagnostics,
        "run_remote_command",
        lambda *args, **kwargs: subprocess.CompletedProcess(args=args, returncode=0, stdout="ok", stderr=""),
    )

    results = edge_diagnostics.sequence_check("example.com", ssh_target="ops@example.com")
    assert any(result.name == "Firewall" for result in results)
    assert all(result.ok for result in results)
