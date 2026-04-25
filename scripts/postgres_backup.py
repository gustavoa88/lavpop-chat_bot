#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from app.postgres_ops import backup_filename, load_postgres_connection_info, run_pg_dump


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Cria backup custom-format do PostgreSQL.")
    parser.add_argument(
        "--output-dir",
        default="backups/postgres",
        help="Diretório destino do backup (padrão: backups/postgres).",
    )
    parser.add_argument(
        "--prefix",
        default="lavpop_chatbot",
        help="Prefixo do arquivo de backup (padrão: lavpop_chatbot).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        connection = load_postgres_connection_info(os.environ)
        output_dir = Path(args.output_dir)
        output_file = output_dir / backup_filename(args.prefix)
        run_pg_dump(connection, output_file)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(str(output_file))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

