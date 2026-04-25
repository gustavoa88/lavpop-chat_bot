# Production Operation Checklist

## Borda e acesso

- Publicar o app atrás de Nginx.
- Expor apenas `/webhook/meta` publicamente.
- Proteger `/metrics` e `/health/*` com allowlist de rede interna e basic auth.
- Aplicar rate limit no webhook no proxy.

## Banco

- Rodar backup regular com `scripts/postgres_backup.py`.
- Validar restore em staging com `scripts/postgres_restore_drill.py`.
- Manter retenção dos dumps fora do diretório de produção.

## Monitoramento

- Validar `promtool check rules monitoring/prometheus/alerts.yml`.
- Confirmar alertas para indisponibilidade, erro de processamento, falha de assinatura e latência p95.

## Deploy

- Exigir `tests` + `integration-release` antes do deploy.
- Definir `PRODUCTION_BASE_URL` como variable ou secret no ambiente `production` do GitHub.
- Rodar smoke público no CI contra `/`.
- Validar `/health/live`, `/health/ready` e `/health/db` a partir da rede interna ou com acesso operacional autorizado.
- Bloquear release se o smoke público falhar; bloquear operação se qualquer endpoint de saúde interno falhar.

## Recuperação

- Restaurar o último backup validado em caso de corrupção de dados.
- Reexecutar o smoke test após o rollback.
- Registrar causa raiz e ação corretiva.
