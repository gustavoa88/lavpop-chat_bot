from dataclasses import replace

import pytest

from app import main


def test_enforce_production_security_baseline_raises_when_meta_require_app_secret_is_false(monkeypatch):
    patched = replace(main.settings, app_env="production", meta_require_app_secret=False)
    monkeypatch.setattr(main, "settings", patched)

    with pytest.raises(RuntimeError):
        main._enforce_production_security_baseline()


def test_enforce_production_security_baseline_allows_non_production(monkeypatch):
    patched = replace(main.settings, app_env="dev", meta_require_app_secret=False)
    monkeypatch.setattr(main, "settings", patched)

    main._enforce_production_security_baseline()
