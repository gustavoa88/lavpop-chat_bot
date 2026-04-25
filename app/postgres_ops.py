"""Helpers para backup e restore do PostgreSQL."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from subprocess import run
from typing import Mapping
from urllib.parse import unquote, urlparse
import os


@dataclass(frozen=True)
class PostgresConnectionInfo:
    host: str
    port: int
    dbname: str
    user: str
    password: str

    def as_pg_env(self) -> dict[str, str]:
        env = {
            "PGHOST": self.host,
            "PGPORT": str(self.port),
            "PGDATABASE": self.dbname,
            "PGUSER": self.user,
        }
        if self.password:
            env["PGPASSWORD"] = self.password
        return env


def load_postgres_connection_info(env: Mapping[str, str]) -> PostgresConnectionInfo:
    database_url = (env.get("DATABASE_URL") or "").strip()
    if database_url:
        parsed = urlparse(database_url)
        if parsed.scheme not in {"postgres", "postgresql"}:
            raise ValueError("DATABASE_URL inválida: use schema postgres:// ou postgresql://.")

        return PostgresConnectionInfo(
            host=parsed.hostname or (env.get("DB_HOST") or "127.0.0.1"),
            port=parsed.port or int(env.get("DB_PORT") or "5432"),
            dbname=unquote(parsed.path.lstrip("/")) or (env.get("DB_NAME") or "lavpop_chatbot"),
            user=unquote(parsed.username) if parsed.username else (env.get("DB_USER") or "postgres"),
            password=unquote(parsed.password) if parsed.password is not None else (env.get("DB_PASSWORD") or "postgres"),
        )

    return PostgresConnectionInfo(
        host=env.get("DB_HOST") or "127.0.0.1",
        port=int(env.get("DB_PORT") or "5432"),
        dbname=env.get("DB_NAME") or "lavpop_chatbot",
        user=env.get("DB_USER") or "postgres",
        password=env.get("DB_PASSWORD") or "postgres",
    )


def backup_filename(prefix: str = "lavpop_chatbot") -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{prefix}-{timestamp}.dump"


def run_pg_dump(connection: PostgresConnectionInfo, output_file: Path) -> None:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    run(
        [
            "pg_dump",
            "--format=custom",
            "--no-owner",
            "--no-acl",
            "--file",
            str(output_file),
        ],
        check=True,
        env={**os.environ, **connection.as_pg_env()},
    )


def run_pg_restore(connection: PostgresConnectionInfo, input_file: Path) -> None:
    run(
        [
            "pg_restore",
            "--clean",
            "--if-exists",
            "--no-owner",
            "--no-acl",
            "--dbname",
            connection.dbname,
            str(input_file),
        ],
        check=True,
        env={**os.environ, **connection.as_pg_env()},
    )
