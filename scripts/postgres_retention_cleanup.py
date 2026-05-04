#!/usr/bin/env python3
"""Limpeza de retenção de dados operacionais conforme política.

Tabelas alvo:
- chatbot.webhook_event_dedup: 30 dias
- chatbot.mensagens: 180 dias
- chatbot.log_conversas: 180 dias
"""

import argparse
import os
from dataclasses import dataclass

import psycopg2


@dataclass(frozen=True)
class RetentionTarget:
    table: str
    timestamp_column: str
    interval: str


TARGETS = (
    RetentionTarget("chatbot.webhook_event_dedup", "processed_at", "30 days"),
    RetentionTarget("chatbot.mensagens", "created_at", "180 days"),
    RetentionTarget("chatbot.log_conversas", "created_at", "180 days"),
)


def _build_dsn() -> str:
    if os.getenv("DATABASE_URL"):
        return os.getenv("DATABASE_URL", "")

    host = os.getenv("DB_HOST", "127.0.0.1")
    port = os.getenv("DB_PORT", "5432")
    dbname = os.getenv("DB_NAME", "lavpop_chatbot")
    user = os.getenv("DB_USER", "postgres")
    password = os.getenv("DB_PASSWORD", "postgres")
    return f"dbname={dbname} user={user} password={password} host={host} port={port}"


def _eligible_count(cur, target: RetentionTarget) -> int:
    cur.execute(
        f"SELECT COUNT(*) FROM {target.table} WHERE {target.timestamp_column} < NOW() - INTERVAL %s",
        (target.interval,),
    )
    return int(cur.fetchone()[0])


def _delete_batch(cur, target: RetentionTarget, batch_size: int) -> int:
    cur.execute(
        f"""
        WITH doomed AS (
            SELECT ctid
              FROM {target.table}
             WHERE {target.timestamp_column} < NOW() - INTERVAL %s
             LIMIT %s
        )
        DELETE FROM {target.table} t
         USING doomed
         WHERE t.ctid = doomed.ctid
        """,
        (target.interval, batch_size),
    )
    return int(cur.rowcount or 0)


def main() -> int:
    parser = argparse.ArgumentParser(description="Limpeza de retenção para tabelas operacionais")
    parser.add_argument("--apply", action="store_true", help="Executa deleção (default: dry-run)")
    parser.add_argument("--batch-size", type=int, default=1000, help="Tamanho do lote de deleção")
    args = parser.parse_args()

    dsn = _build_dsn()
    with psycopg2.connect(dsn) as conn:
        with conn.cursor() as cur:
            total_deleted = 0
            for target in TARGETS:
                eligible = _eligible_count(cur, target)
                print(f"[retention] tabela={target.table} elegiveis={eligible} intervalo={target.interval}")
                if not args.apply or eligible == 0:
                    continue

                deleted_for_table = 0
                while True:
                    deleted = _delete_batch(cur, target, max(1, args.batch_size))
                    conn.commit()
                    deleted_for_table += deleted
                    total_deleted += deleted
                    if deleted == 0:
                        break
                print(f"[retention] tabela={target.table} removidos={deleted_for_table}")

    if args.apply:
        print(f"[retention] total_removido={total_deleted}")
    else:
        print("[retention] dry-run finalizado sem remoções")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
