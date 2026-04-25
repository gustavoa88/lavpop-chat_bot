#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from app.postgres_ops import load_postgres_connection_info, run_pg_restore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Restaura um backup custom-format no PostgreSQL.")
    parser.add_argument("backup_file", help="Arquivo .dump gerado pelo backup.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        backup_file = Path(args.backup_file)
        if not backup_file.exists():
            raise FileNotFoundError(f"Backup não encontrado: {backup_file}")
        connection = load_postgres_connection_info(os.environ)
        run_pg_restore(connection, backup_file)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"Restaurado em {connection.dbname}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

