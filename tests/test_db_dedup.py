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
