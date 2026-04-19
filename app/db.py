from contextlib import contextmanager
import logging
import time
from typing import Any, Iterator, Optional

import psycopg2
import psycopg2.extras
from psycopg2.pool import ThreadedConnectionPool

from app.config import Settings

logger = logging.getLogger("meta_chatbot")


class Database:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._pool: Optional[ThreadedConnectionPool] = None
        self._dedup_table_warning_logged = False

    def start(self) -> None:
        if self._pool is not None:
            return
        self._pool = ThreadedConnectionPool(
            minconn=self._settings.db_min_conn,
            maxconn=self._settings.db_max_conn,
            host=self._settings.db_host,
            port=self._settings.db_port,
            dbname=self._settings.db_name,
            user=self._settings.db_user,
            password=self._settings.db_password,
            connect_timeout=self._settings.db_connect_timeout,
            application_name="meta_chatbot",
        )

    def stop(self) -> None:
        if self._pool is None:
            return
        self._pool.closeall()
        self._pool = None

    @contextmanager
    def connection(self) -> Iterator[Any]:
        if self._pool is None:
            raise RuntimeError("Database pool not initialized")
        conn = self._pool.getconn()
        try:
            yield conn
        finally:
            self._pool.putconn(conn)

    def fetchall(self, query: str, params: tuple = ()) -> list[dict]:
        with self.connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(query, params)
                return [dict(x) for x in cur.fetchall()]

    def fetchone(self, query: str, params: tuple = ()) -> Optional[dict]:
        with self.connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(query, params)
                row = cur.fetchone()
                return dict(row) if row else None

    def execute(self, query: str, params: tuple = ()) -> None:
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
            conn.commit()

    def try_register_webhook_event(
        self,
        event_key: str,
        payload_hash: str,
        source: str = "meta_webhook",
    ) -> bool:
        try:
            with self.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO chatbot.webhook_event_dedup (
                            event_key, payload_hash, source, processed_at
                        ) VALUES (%s, %s, %s, NOW())
                        ON CONFLICT (event_key) DO NOTHING
                        RETURNING event_key
                        """,
                        (event_key, payload_hash, source),
                    )
                    inserted = cur.fetchone() is not None
                conn.commit()
            return inserted
        except psycopg2.errors.UndefinedTable:
            if not self._dedup_table_warning_logged:
                logger.warning(
                    "Tabela de deduplicação do webhook não encontrada "
                    "(chatbot.webhook_event_dedup). "
                    "Prosseguindo sem idempotência até aplicar db/schema.sql."
                )
                self._dedup_table_warning_logged = True
            return True

    def is_ready(self) -> bool:
        try:
            with self.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
                    cur.fetchone()
            return True
        except Exception:
            return False

    def healthcheck(self) -> dict[str, Any]:
        started_at = time.perf_counter()
        try:
            with self.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
                    cur.fetchone()
            latency_ms = round((time.perf_counter() - started_at) * 1000, 2)
            return {
                "ready": True,
                "latency_ms": latency_ms,
            }
        except Exception as exc:
            latency_ms = round((time.perf_counter() - started_at) * 1000, 2)
            return {
                "ready": False,
                "latency_ms": latency_ms,
                "error": str(exc),
            }
