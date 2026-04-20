from app.config import load_settings


def test_load_settings_uses_inactivity_defaults(monkeypatch):
    monkeypatch.delenv("INACTIVITY_TIMEOUT_MINUTES", raising=False)
    monkeypatch.delenv("INACTIVITY_CHECK_INTERVAL_SECONDS", raising=False)

    settings = load_settings()

    assert settings.inactivity_timeout_minutes == 15
    assert settings.inactivity_check_interval_seconds == 60


def test_load_settings_reads_inactivity_values_from_env(monkeypatch):
    monkeypatch.setenv("INACTIVITY_TIMEOUT_MINUTES", "30")
    monkeypatch.setenv("INACTIVITY_CHECK_INTERVAL_SECONDS", "120")

    settings = load_settings()

    assert settings.inactivity_timeout_minutes == 30
    assert settings.inactivity_check_interval_seconds == 120


def test_load_settings_reads_app_env(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")

    settings = load_settings()

    assert settings.app_env == "production"


def test_load_settings_uses_observability_internal_only_default(monkeypatch):
    monkeypatch.delenv("OBSERVABILITY_INTERNAL_ONLY", raising=False)

    settings = load_settings()

    assert settings.observability_internal_only is True


def test_load_settings_reads_observability_internal_only_from_env(monkeypatch):
    monkeypatch.setenv("OBSERVABILITY_INTERNAL_ONLY", "false")

    settings = load_settings()

    assert settings.observability_internal_only is False


def test_load_settings_uses_proxy_header_defaults(monkeypatch):
    monkeypatch.delenv("TRUST_PROXY_HEADERS", raising=False)
    monkeypatch.delenv("TRUSTED_PROXY_CIDRS", raising=False)

    settings = load_settings()

    assert settings.trust_proxy_headers is False
    assert settings.trusted_proxy_cidrs == ("127.0.0.1/32", "::1/128")


def test_load_settings_reads_proxy_header_values_from_env(monkeypatch):
    monkeypatch.setenv("TRUST_PROXY_HEADERS", "true")
    monkeypatch.setenv("TRUSTED_PROXY_CIDRS", "10.0.0.0/8, 192.168.0.0/16")

    settings = load_settings()

    assert settings.trust_proxy_headers is True
    assert settings.trusted_proxy_cidrs == ("10.0.0.0/8", "192.168.0.0/16")
