from contextlib import contextmanager

import psycopg2

from app.config import Settings
from app.db import Database


class _CursorRaisingUndefinedTable:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params):
        raise psycopg2.errors.UndefinedTable("relation does not exist")


class _ConnectionWithFailingCursor:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return _CursorRaisingUndefinedTable()

    def commit(self):
        return None


class _CursorCollectingStatements:
    def __init__(self, fetchone_values=None):
        self.statements = []
        self._fetchone_values = list(fetchone_values or [])

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=()):
        self.statements.append(" ".join(str(query).split()))

    def fetchone(self):
        if self._fetchone_values:
            return self._fetchone_values.pop(0)
        return (None,)


class _ConnectionCollectingStatements:
    def __init__(self, fetchone_values=None):
        self.cursor_obj = _CursorCollectingStatements(fetchone_values=fetchone_values)
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.committed = True


class _CursorRaiseInsufficientPrivilege:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=()):
        query_str = str(query).lower()
        if "to_regclass" in query_str:
            return None
        raise psycopg2.errors.InsufficientPrivilege("permission denied")

    def fetchone(self):
        return (None,)


class _ConnectionWithPrivilegeError:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return _CursorRaiseInsufficientPrivilege()

    def commit(self):
        return None


def _build_settings() -> Settings:
    return Settings(
        openai_api_key="",
        openai_model="gpt-4.1-mini",
        meta_verify_token="verify-token",
        meta_whatsapp_token="",
        meta_phone_number_id="",
        meta_app_secret="",
        meta_validate_signature=True,
        meta_require_app_secret=False,
        db_host="127.0.0.1",
        db_port=5432,
        db_name="lavpop_chatbot",
        db_user="postgres",
        db_password="postgres",
        db_min_conn=1,
        db_max_conn=5,
        db_connect_timeout=3,
    )


def test_try_register_webhook_event_allows_processing_when_table_is_missing():
    db = Database(_build_settings())

    @contextmanager
    def fake_connection():
        yield _ConnectionWithFailingCursor()

    db.connection = fake_connection

    should_process = db.try_register_webhook_event(
        event_key="meta_msg_id:1",
        payload_hash="0" * 64,
    )

    assert should_process is True


def test_ensure_minimum_schema_creates_webhook_dedup_objects():
    db = Database(_build_settings())
    fake_conn = _ConnectionCollectingStatements(fetchone_values=[(None,)])

    @contextmanager
    def fake_connection():
        yield fake_conn

    db.connection = fake_connection

    db.ensure_minimum_schema()

    all_sql = "\n".join(fake_conn.cursor_obj.statements).lower()
    assert "create schema if not exists chatbot" in all_sql
    assert "create table if not exists chatbot.webhook_event_dedup" in all_sql
    assert "create index if not exists idx_webhook_event_dedup_processed_at" in all_sql
    assert fake_conn.committed is True


def test_ensure_minimum_schema_skips_ddl_when_table_already_exists():
    db = Database(_build_settings())
    fake_conn = _ConnectionCollectingStatements(fetchone_values=[("chatbot.webhook_event_dedup",)])

    @contextmanager
    def fake_connection():
        yield fake_conn

    db.connection = fake_connection

    db.ensure_minimum_schema()

    all_sql = "\n".join(fake_conn.cursor_obj.statements).lower()
    assert "to_regclass('chatbot.webhook_event_dedup')" in all_sql
    assert "create table if not exists chatbot.webhook_event_dedup" not in all_sql
    assert fake_conn.committed is False


def test_ensure_minimum_schema_logs_warning_when_user_lacks_ddl_permission(caplog):
    db = Database(_build_settings())

    @contextmanager
    def fake_connection():
        yield _ConnectionWithPrivilegeError()

    db.connection = fake_connection

    db.ensure_minimum_schema()

    assert "sem permissão para criar schema/tabela mínima de deduplicação" in caplog.text
