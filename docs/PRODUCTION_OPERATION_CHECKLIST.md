# Production Operation Checklist

Use esta checklist como critério objetivo de GO/NO-GO para produção controlada.
Itens marcados como **bloqueador** precisam estar concluídos antes de iniciar ou
manter operação real.

## Borda e acesso

- [ ] **Bloqueador:** publicar o app atrás de Nginx ou borda equivalente.
- [ ] **Bloqueador:** expor publicamente apenas `/webhook/meta` e `/`.
- [ ] **Bloqueador:** manter `/docs`, `/redoc` e `/openapi.json` desabilitados em produção.
- [ ] **Bloqueador:** proteger `/metrics` e `/health/*` com allowlist de rede interna e autenticação operacional.
- [ ] **Bloqueador:** se `/operator` estiver habilitado, proteger por rede interna e `OPERATOR_PANEL_TOKEN`.
- [ ] **Bloqueador:** aplicar rate limit no webhook no proxy.
- [ ] Validar `nginx -t` antes de recarregar o serviço.

## Banco

- [ ] **Bloqueador:** rodar backup regular com `scripts/postgres_backup.py` ou rotina equivalente.
- [ ] **Bloqueador:** validar restore em staging com `scripts/postgres_restore_drill.py` ou rotina equivalente.
- [ ] **Bloqueador:** aplicar migrations em `db/migrations/` antes do restart de produção.
- [ ] Manter retenção dos dumps fora do diretório de produção.
- [ ] Seguir `docs/LOGGING_AND_DATA_RETENTION_POLICY.md` para retenção de dados operacionais.

## Monitoramento

- [ ] **Bloqueador:** validar `promtool check rules monitoring/prometheus/alerts.yml`.
- [ ] **Bloqueador:** confirmar alertas para indisponibilidade, erro de processamento, falha de assinatura e latência p95.
- [ ] Confirmar que `/metrics` é coletado apenas por origem autorizada.

## Deploy

- [ ] **Bloqueador:** exigir `quality` + `tests` + `integration-release` antes do deploy.
- [ ] **Bloqueador:** ativar branch protection/ruleset em `main` bloqueando merge com checks pendentes ou falhando.
- [ ] **Bloqueador:** definir `PRODUCTION_BASE_URL` como variable ou secret no ambiente `production` do GitHub.
- [ ] **Bloqueador:** definir `META_APP_SECRET` como secret no ambiente `production` do GitHub.
- [ ] **Bloqueador:** manter `APP_ENV=production`, `META_VALIDATE_SIGNATURE=true`, `META_REQUIRE_APP_SECRET=true` e `APP_DEBUG_LOG_MODE=false`.
- [ ] Se `OPERATOR_PANEL_ENABLED=true`, definir `OPERATOR_PANEL_TOKEN` fora do repositório.
- [ ] Rodar smoke público no CI contra `/`.
- [ ] Executar deploy manual supervisionado e registrar commit, horário UTC, responsável e resultado.
- [ ] Validar `/health/live`, `/health/ready` e `/health/db` a partir da rede interna ou com acesso operacional autorizado.
- [ ] Bloquear release se o smoke público falhar; bloquear operação se qualquer endpoint de saúde interno falhar.

## Recuperação

- [ ] **Bloqueador:** restaurar o último backup validado em caso de corrupção de dados.
- [ ] Reexecutar o smoke test após o rollback.
- [ ] Registrar causa raiz e ação corretiva.

## Evidência de go-live

- [ ] Preencher `docs/PRODUCTION_CONTROLLED_GO_LIVE_2026-04-25.md` com run URL, commit, validações de borda, alertas e restore drill.
- [ ] Reavaliar a classificação se houver aumento relevante de volume, incidente SEV-1/SEV-2 ou mudança de proxy/secrets/schema.
