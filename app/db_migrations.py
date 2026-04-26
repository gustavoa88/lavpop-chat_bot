"""Runner simples para migrações SQL versionadas do PostgreSQL."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Mapping

import psycopg2

from app.postgres_ops import PostgresConnectionInfo


SCHEMA_MIGRATIONS_TABLE_SQL = """
CREATE SCHEMA IF NOT EXISTS chatbot;

CREATE TABLE IF NOT EXISTS chatbot.schema_migrations (
  version VARCHAR(120) PRIMARY KEY,
  filename TEXT NOT NULL,
  checksum CHAR(64) NOT NULL,
  applied_at TIMESTAMP NOT NULL DEFAULT NOW()
);
"""


@dataclass(frozen=True)
class Migration:
    version: str
    filename: str
    path: Path
    checksum: str
    sql: str


@dataclass(frozen=True)
class MigrationPlanItem:
    migration: Migration
    status: str


def load_sql_migrations(migrations_dir: Path) -> list[Migration]:
    if not migrations_dir.exists():
        raise FileNotFoundError(f"Diretório de migrações não encontrado: {migrations_dir}")

    migrations: list[Migration] = []
    seen_versions: set[str] = set()
    for path in sorted(migrations_dir.glob("*.sql")):
        version = path.stem
        if version in seen_versions:
            raise ValueError(f"Migração duplicada: {version}")
        seen_versions.add(version)

        sql = path.read_text(encoding="utf-8")
        checksum = hashlib.sha256(sql.encode("utf-8")).hexdigest()
        migrations.append(
            Migration(
                version=version,
                filename=path.name,
                path=path,
                checksum=checksum,
                sql=sql,
            )
        )

    return migrations


def plan_migrations(
    migrations: list[Migration],
    applied_checksums_by_version: Mapping[str, str],
) -> list[MigrationPlanItem]:
    plan: list[MigrationPlanItem] = []
    for migration in migrations:
        applied_checksum = applied_checksums_by_version.get(migration.version)
        if applied_checksum is None:
            plan.append(MigrationPlanItem(migration=migration, status="pending"))
            continue
        if applied_checksum != migration.checksum:
            raise RuntimeError(
                "Checksum divergente para migração já aplicada "
                f"{migration.version}: banco={applied_checksum} arquivo={migration.checksum}"
            )
        plan.append(MigrationPlanItem(migration=migration, status="applied"))
    return plan


def _fetch_applied_checksums(conn) -> dict[str, str]:
    with conn.cursor() as cur:
        cur.execute(SCHEMA_MIGRATIONS_TABLE_SQL)
        cur.execute("SELECT version, checksum FROM chatbot.schema_migrations")
        rows = cur.fetchall()
    conn.commit()
    return {version: checksum for version, checksum in rows}


def apply_pending_migrations(conn, migrations: list[Migration]) -> list[MigrationPlanItem]:
    applied_checksums = _fetch_applied_checksums(conn)
    plan = plan_migrations(migrations, applied_checksums)

    for item in plan:
        if item.status != "pending":
            continue

        migration = item.migration
        try:
            with conn.cursor() as cur:
                cur.execute(migration.sql)
                cur.execute(
                    """
                    INSERT INTO chatbot.schema_migrations (version, filename, checksum, applied_at)
                    VALUES (%s, %s, %s, NOW())
                    """,
                    (migration.version, migration.filename, migration.checksum),
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    return plan


def run_migrations(
    connection: PostgresConnectionInfo,
    migrations_dir: Path,
) -> list[MigrationPlanItem]:
    migrations = load_sql_migrations(migrations_dir)
    conn = psycopg2.connect(
        host=connection.host,
        port=connection.port,
        dbname=connection.dbname,
        user=connection.user,
        password=connection.password,
        connect_timeout=10,
        application_name="meta_chatbot_migrations",
    )
    try:
        return apply_pending_migrations(conn, migrations)
    finally:
        conn.close()
