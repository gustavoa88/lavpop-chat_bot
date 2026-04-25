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
        if self._settings.app_env not in {"prod", "production"}:
            self.ensure_minimum_schema()
        self.assert_required_schema()

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
        except Exception:
            try:
                conn.rollback()
            except Exception:
                logger.exception("Falha ao executar rollback de conexão PostgreSQL.")
            raise
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

    def ensure_minimum_schema(self) -> None:
        """
        Garante objetos mínimos de funcionamento para produção:
        - schema chatbot
        - tabela de deduplicação de eventos do webhook

        Isso evita processamento duplicado caso o deploy seja realizado antes de
        aplicar o db/schema.sql completo.
        """
        ddl_statements = [
            "CREATE SCHEMA IF NOT EXISTS chatbot",
            """
            CREATE TABLE IF NOT EXISTS chatbot.webhook_event_dedup (
              event_key VARCHAR(255) PRIMARY KEY,
              payload_hash CHAR(64) NOT NULL,
              source VARCHAR(60) NOT NULL DEFAULT 'meta_webhook',
              processed_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_webhook_event_dedup_processed_at
              ON chatbot.webhook_event_dedup (processed_at DESC)
            """,
            """
            CREATE TABLE IF NOT EXISTS chatbot.mensagens (
              id BIGSERIAL PRIMARY KEY,
              event_key VARCHAR(255),
              telefone VARCHAR(50) NOT NULL,
              nome_contato VARCHAR(120),
              direcao VARCHAR(20) NOT NULL,
              origem VARCHAR(40) NOT NULL,
              tipo VARCHAR(40) NOT NULL DEFAULT 'text',
              conteudo_texto TEXT,
              payload_json JSONB,
              status VARCHAR(40) NOT NULL DEFAULT 'received',
              resposta_origem VARCHAR(40),
              regra_nome VARCHAR(120),
              intencao VARCHAR(120),
              created_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """,
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_mensagens_event_key_unique
              ON chatbot.mensagens (event_key)
              WHERE event_key IS NOT NULL
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_mensagens_telefone_created
              ON chatbot.mensagens (telefone, created_at DESC)
            """,
            """
            DO $$
            BEGIN
              IF to_regclass('chatbot.contexto_cliente') IS NOT NULL THEN
                ALTER TABLE chatbot.contexto_cliente
                  ADD COLUMN IF NOT EXISTS modo_conversa VARCHAR(30) NOT NULL DEFAULT 'bot',
                  ADD COLUMN IF NOT EXISTS bot_pausado_ate TIMESTAMP,
                  ADD COLUMN IF NOT EXISTS ultimo_handoff_em TIMESTAMP,
                  ADD COLUMN IF NOT EXISTS ultimo_handoff_motivo VARCHAR(120),
                  ADD COLUMN IF NOT EXISTS ultima_origem_mensagem VARCHAR(40);

                CREATE INDEX IF NOT EXISTS idx_contexto_cliente_modo
                  ON chatbot.contexto_cliente (modo_conversa, ultima_interacao DESC);
              END IF;
            END $$;
            """,
        ]
        try:
            with self.connection() as conn:
                with conn.cursor() as cur:
                    for statement in ddl_statements:
                        cur.execute(statement)
                conn.commit()
        except psycopg2.errors.InsufficientPrivilege:
            logger.warning(
                "Usuário do banco sem permissão para criar schema/tabela mínima "
                "de deduplicação. Aplique db/schema.sql com um usuário privilegiado "
                "ou conceda permissões DDL ao usuário da aplicação."
            )
        except Exception:
            logger.exception(
                "Falha ao garantir schema mínimo de deduplicação do webhook. "
                "A aplicação seguirá em modo de compatibilidade."
            )

    def validate_required_schema(self) -> list[str]:
        required_columns = {
            "chatbot.webhook_event_dedup": {"event_key", "payload_hash", "source", "processed_at"},
            "chatbot.mensagens": {
                "event_key",
                "telefone",
                "direcao",
                "origem",
                "tipo",
                "conteudo_texto",
                "status",
            },
            "chatbot.contexto_cliente": {"telefone", "modo_conversa", "ultima_interacao", "status"},
            "chatbot.log_conversas": {"telefone", "mensagem_cliente", "resposta_bot", "origem_resposta"},
        }
        problems: list[str] = []

        try:
            with self.connection() as conn:
                with conn.cursor() as cur:
                    for relation, columns in required_columns.items():
                        schema_name, table_name = relation.split(".", 1)
                        cur.execute("SELECT to_regclass(%s)", (relation,))
                        row = cur.fetchone()
                        if not row or not row[0]:
                            problems.append(f"tabela ausente: {relation}")
                            continue

                        cur.execute(
                            """
                            SELECT column_name
                              FROM information_schema.columns
                             WHERE table_schema = %s
                               AND table_name = %s
                            """,
                            (schema_name, table_name),
                        )
                        existing_columns = {item[0] for item in cur.fetchall()}
                        missing_columns = sorted(columns - existing_columns)
                        if missing_columns:
                            problems.append(
                                f"colunas ausentes em {relation}: {', '.join(missing_columns)}"
                            )
        except Exception as exc:
            problems.append(f"falha ao validar schema obrigatório: {exc}")

        return problems

    def assert_required_schema(self) -> None:
        problems = self.validate_required_schema()
        if not problems:
            return

        message = "Schema obrigatório do banco incompatível: " + "; ".join(problems)
        if self._settings.app_env in {"prod", "production"}:
            raise RuntimeError(message)

        logger.warning("%s", message)

    def _webhook_dedup_table_exists(self) -> bool:
        try:
            with self.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT to_regclass('chatbot.webhook_event_dedup')")
                    row = cur.fetchone()
                    return bool(row and row[0])
        except Exception:
            return False

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
        except psycopg2.errors.UndefinedColumn:
            if not self._dedup_table_warning_logged:
                logger.warning(
                    "Estrutura da tabela de deduplicação incompatível "
                    "(coluna esperada ausente em chatbot.webhook_event_dedup). "
                    "Prosseguindo sem idempotência até aplicar db/schema.sql."
                )
                self._dedup_table_warning_logged = True
            return True
        except RuntimeError as exc:
            if str(exc) == "Database pool not initialized":
                if not self._dedup_table_warning_logged:
                    logger.warning(
                        "Pool de banco não inicializado ao registrar deduplicação de webhook. "
                        "Prosseguindo sem idempotência em modo compatibilidade."
                    )
                    self._dedup_table_warning_logged = True
                return True
            raise
        except Exception:
            logger.exception(
                "Falha inesperada ao registrar deduplicação de webhook. "
                "Prosseguindo sem idempotência em modo compatibilidade."
            )
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
