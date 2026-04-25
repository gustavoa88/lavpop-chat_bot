#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys

from app.production_checks import DEFAULT_SMOKE_PATHS, run_production_smoke_checks


def _parse_headers(items: list[str]) -> dict[str, str]:
    headers: dict[str, str] = {}
    for item in items:
        if "=" not in item:
            raise ValueError(f"Header inválido: {item!r}. Use NOME=VALOR.")
        name, value = item.split("=", 1)
        name = name.strip()
        value = value.strip()
        if not name:
            raise ValueError(f"Header inválido: {item!r}. O nome não pode ser vazio.")
        headers[name] = value
    return headers


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Executa smoke tests de produção.")
    parser.add_argument("--base-url", required=True, help="URL base da aplicação em produção.")
    parser.add_argument(
        "--timeout",
        type=float,
        default=5.0,
        help="Timeout em segundos por requisição (padrão: 5).",
    )
    parser.add_argument(
        "--path",
        action="append",
        dest="paths",
        help="Caminho adicional para validar. Pode ser repetido.",
    )
    parser.add_argument(
        "--header",
        action="append",
        default=[],
        help="Header extra no formato Nome=Valor. Pode ser repetido.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    paths = tuple(args.paths) if args.paths else DEFAULT_SMOKE_PATHS
    try:
        headers = _parse_headers(args.header)
        results = run_production_smoke_checks(
            args.base_url,
            timeout_seconds=args.timeout,
            paths=paths,
            headers=headers,
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    for result in results:
        status = "OK" if result.ok else "FAIL"
        extra = f" body={result.body_preview!r}" if result.body_preview else ""
        print(f"{status} {result.status_code} {result.path} -> {result.url}{extra}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
