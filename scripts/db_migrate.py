#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from app.db_migrations import run_migrations
from app.postgres_ops import load_postgres_connection_info


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Aplica migrações SQL versionadas do PostgreSQL.")
    parser.add_argument(
        "--migrations-dir",
        default="db/migrations",
        help="Diretório das migrações SQL (padrão: db/migrations).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        connection = load_postgres_connection_info(os.environ)
        plan = run_migrations(connection, Path(args.migrations_dir))
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    for item in plan:
        print(f"{item.status}: {item.migration.filename}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
