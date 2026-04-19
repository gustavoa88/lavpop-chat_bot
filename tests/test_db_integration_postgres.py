import os
import uuid
from pathlib import Path

import psycopg2
import pytest

from app.config import Settings
from app.db import Database

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_SQL = ROOT / "db" / "schema.sql"
TEST_DSN = os.getenv("TEST_POSTGRES_DSN")

pytestmark = pytest.mark.integration


def _settings_from_dsn(dsn: str) -> Settings:
    params = psycopg2.extensions.parse_dsn(dsn)
    return Settings(
        openai_api_key="",
        openai_model="gpt-4.1-mini",
        meta_verify_token="verify-token",
        meta_whatsapp_token="",
        meta_phone_number_id="",
        meta_app_secret="",
        meta_validate_signature=True,
        meta_require_app_secret=False,
        db_host=params.get("host", "127.0.0.1"),
        db_port=int(params.get("port", 5432)),
        db_name=params.get("dbname", "postgres"),
        db_user=params.get("user", "postgres"),
        db_password=params.get("password", ""),
        db_min_conn=1,
        db_max_conn=2,
        db_connect_timeout=3,
    )


def _prepare_schema(dsn: str) -> None:
    sql = SCHEMA_SQL.read_text(encoding="utf-8")
    with psycopg2.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)


@pytest.fixture(scope="module")
def integration_db() -> Database:
    if not TEST_DSN:
        pytest.skip("Defina TEST_POSTGRES_DSN para executar testes de integração com PostgreSQL.")

    _prepare_schema(TEST_DSN)
    db = Database(_settings_from_dsn(TEST_DSN))
    db.start()
    yield db
    db.stop()


def test_healthcheck_and_ready(integration_db: Database):
    assert integration_db.is_ready() is True

    health = integration_db.healthcheck()
    assert health["ready"] is True
    assert isinstance(health["latency_ms"], float)


def test_execute_fetchone_and_fetchall(integration_db: Database):
    key = f"integration:{uuid.uuid4()}"

    integration_db.execute(
        """
        INSERT INTO chatbot.webhook_event_dedup (event_key, payload_hash, source)
        VALUES (%s, %s, %s)
        ON CONFLICT (event_key) DO NOTHING
        """,
        (key, "a" * 64, "pytest"),
    )

    row = integration_db.fetchone(
        "SELECT event_key, payload_hash, source FROM chatbot.webhook_event_dedup WHERE event_key = %s",
        (key,),
    )
    assert row is not None
    assert row["event_key"] == key
    assert row["payload_hash"] == "a" * 64
    assert row["source"] == "pytest"

    rows = integration_db.fetchall(
        "SELECT event_key FROM chatbot.webhook_event_dedup WHERE event_key = %s",
        (key,),
    )
    assert len(rows) == 1
    assert rows[0]["event_key"] == key


def test_try_register_webhook_event_enforces_idempotency(integration_db: Database):
    key = f"meta_msg_id:{uuid.uuid4()}"
    first = integration_db.try_register_webhook_event(key, "b" * 64, "pytest")
    second = integration_db.try_register_webhook_event(key, "b" * 64, "pytest")

    assert first is True
    assert second is False
