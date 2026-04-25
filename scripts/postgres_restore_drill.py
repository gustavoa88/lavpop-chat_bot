#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

from app.postgres_ops import load_postgres_connection_info, run_pg_dump, run_pg_restore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Executa backup e restore de teste do PostgreSQL.")
    parser.add_argument(
        "--target-database-url",
        required=True,
        help="DATABASE_URL do banco de staging usado no teste de restore.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        source_connection = load_postgres_connection_info(os.environ)
        target_env = dict(os.environ)
        target_env["DATABASE_URL"] = args.target_database_url
        target_connection = load_postgres_connection_info(target_env)

        with tempfile.TemporaryDirectory(prefix="lavpop-chatbot-restore-drill-") as tmpdir:
            backup_file = Path(tmpdir) / "restore-drill.dump"
            run_pg_dump(source_connection, backup_file)
            run_pg_restore(target_connection, backup_file)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print("Restore drill concluído com sucesso.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
