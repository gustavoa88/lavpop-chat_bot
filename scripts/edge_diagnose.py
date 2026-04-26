#!/usr/bin/env python3
from __future__ import annotations

import argparse

from app.edge_diagnostics import sequence_check


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Executa diagnóstico sequencial de DNS, Nginx, firewall e serviço."
    )
    parser.add_argument("--domain", required=True, help="Domínio público do chatbot.")
    parser.add_argument(
        "--public-url",
        help="URL pública a validar. Se omitida, usa http://<domain>.",
    )
    parser.add_argument(
        "--ssh-target",
        help="Destino SSH para checar Nginx, firewall e serviço no host remoto.",
    )
    parser.add_argument("--ssh-port", type=int, default=22, help="Porta SSH (padrão: 22).")
    parser.add_argument(
        "--service-name",
        default="lavpop-chatbot",
        help="Nome do serviço systemd da aplicação.",
    )
    parser.add_argument(
        "--app-port",
        type=int,
        default=8000,
        help="Porta local da aplicação no host remoto.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=5.0,
        help="Timeout por requisição HTTP em segundos.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    results = sequence_check(
        args.domain,
        public_url=args.public_url,
        ssh_target=args.ssh_target,
        ssh_port=args.ssh_port,
        service_name=args.service_name,
        app_port=args.app_port,
        timeout_seconds=args.timeout,
    )

    failures = []
    for result in results:
        status = "OK" if result.ok else "FAIL"
        print(f"{status} {result.name}: {result.detail}")
        if not result.ok:
            failures.append(result.name)

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
