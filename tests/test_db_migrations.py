from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from app.db_migrations import load_sql_migrations, plan_migrations


def test_load_sql_migrations_sorts_by_filename_and_calculates_checksum(tmp_path):
    second = tmp_path / "20260425_002_second.sql"
    first = tmp_path / "20260425_001_first.sql"
    second.write_text("SELECT 2;\n", encoding="utf-8")
    first.write_text("SELECT 1;\n", encoding="utf-8")

    migrations = load_sql_migrations(tmp_path)

    assert [migration.filename for migration in migrations] == [
        "20260425_001_first.sql",
        "20260425_002_second.sql",
    ]
    assert migrations[0].version == "20260425_001_first"
    assert migrations[0].checksum == hashlib.sha256(b"SELECT 1;\n").hexdigest()


def test_load_sql_migrations_raises_when_directory_is_missing(tmp_path):
    missing_dir = tmp_path / "missing"

    with pytest.raises(FileNotFoundError):
        load_sql_migrations(missing_dir)


def test_plan_migrations_marks_applied_and_pending(tmp_path):
    first = tmp_path / "20260425_001_first.sql"
    second = tmp_path / "20260425_002_second.sql"
    first.write_text("SELECT 1;\n", encoding="utf-8")
    second.write_text("SELECT 2;\n", encoding="utf-8")
    migrations = load_sql_migrations(tmp_path)

    plan = plan_migrations(
        migrations,
        {migrations[0].version: migrations[0].checksum},
    )

    assert [item.status for item in plan] == ["applied", "pending"]


def test_plan_migrations_rejects_checksum_drift_for_applied_migration(tmp_path):
    migration_file = tmp_path / "20260425_001_first.sql"
    migration_file.write_text("SELECT 1;\n", encoding="utf-8")
    migration = load_sql_migrations(tmp_path)[0]

    with pytest.raises(RuntimeError, match="Checksum divergente"):
        plan_migrations([migration], {migration.version: "0" * 64})


def test_phone_normalization_migration_updates_all_conversation_tables():
    migration = load_sql_migrations(Path("db/migrations"))[-1]

    assert migration.filename == "20260426_001_normalize_phone_numbers.sql"
    assert "regexp_replace(telefone, '[^0-9]', '', 'g')" in migration.sql
    assert "UPDATE chatbot.mensagens" in migration.sql
    assert "UPDATE chatbot.log_conversas" in migration.sql
    assert "tmp_contexto_cliente_phone_normalized" in migration.sql
    assert "DELETE FROM chatbot.contexto_cliente" in migration.sql
