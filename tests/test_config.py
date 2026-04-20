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
