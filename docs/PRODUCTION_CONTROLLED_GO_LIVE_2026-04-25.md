# Go-Live Controlado (25/04/2026)

## Objetivo

Registrar as evidências mínimas para operar o chatbot em produção controlada,
com baixo volume e supervisão operacional. Este documento não classifica o
projeto como produção plena; fila assíncrona, tracing distribuído, teste de
carga amplo e governança completa de migrations continuam como próximos ciclos.

## Critério de decisão

Status atual: **GO condicionado** para produção controlada quando todas as
evidências abaixo estiverem preenchidas com resultado aprovado.

Bloqueadores para iniciar ou manter operação:

- branch `main` sem ruleset/branch protection exigindo os checks de CI;
- release gate falhando no job `Release gate (manual deploy)`;
- `APP_ENV`, assinatura Meta ou `APP_DEBUG_LOG_MODE` fora do baseline estrito;
- `/metrics` ou `/health/*` acessíveis publicamente sem autenticação/autorização;
- `/operator` habilitado publicamente sem rede interna e token operacional;
- `/docs`, `/redoc` ou `/openapi.json` acessíveis publicamente em produção;
- ausência de procedimento validado de backup e restore.

## Evidências obrigatórias

### GitHub e release

- [ ] Branch/ruleset de `main` exige `quality`.
- [ ] Branch/ruleset de `main` exige `tests`.
- [ ] Branch/ruleset de `main` exige `Integration tests (release gate)`.
- [ ] Merge em `main` fica bloqueado com checks pendentes ou falhando.
- [ ] Ambiente `production` possui `PRODUCTION_BASE_URL` como variable ou secret.
- [ ] Ambiente `production` possui `META_APP_SECRET` como secret.
- [ ] Último release gate passou no job `Release gate (manual deploy)`.
- [ ] Deploy manual foi executado conforme `docs/PRODUCTION_OPERATION_CHECKLIST.md`.
- [ ] Smoke público contra `/` retornou HTTP 200.

Evidência esperada:

```text
Data/hora UTC:
Commit:
Run URL:
Resultado:
Responsável:
```

### Borda e acesso operacional

- [ ] Nginx ou borda equivalente está aplicada em produção.
- [ ] `nginx -t` ou validação equivalente passou.
- [ ] `POST /webhook/meta` está exposto publicamente.
- [ ] `/docs`, `/redoc` e `/openapi.json` retornam 404 em produção.
- [ ] `/metrics` retorna 401/403 para origem externa não autorizada.
- [ ] `/health/live`, `/health/ready` e `/health/db` retornam 401/403 para origem externa não autorizada.
- [ ] `/metrics` e `/health/*` respondem pela rede interna ou com autenticação operacional.
- [ ] Se habilitado, `/operator` responde apenas por rede interna/autorizada e exige token.
- [ ] Rate limit do webhook está ativo na borda.
- [ ] `client_max_body_size` está limitado para reduzir payload abusivo.

Evidência esperada:

```text
Data/hora UTC:
Domínio:
Comando externo usado:
Comando interno/autorizado usado:
Resultado:
Responsável:
```

### Segurança runtime

- [ ] `APP_ENV=prod` ou `APP_ENV=production`.
- [ ] `META_VALIDATE_SIGNATURE=true`.
- [ ] `META_REQUIRE_APP_SECRET=true`.
- [ ] `META_APP_SECRET` configurado e não vazio.
- [ ] `APP_DEBUG_LOG_MODE=false`.
- [ ] `OBSERVABILITY_INTERNAL_ONLY=true`.
- [ ] Se `OPERATOR_PANEL_ENABLED=true`, `OPERATOR_PANEL_TOKEN` está definido fora do repositório.
- [ ] `TRUST_PROXY_HEADERS` só está ativo com `TRUSTED_PROXY_CIDRS` restrito aos proxies confiáveis.

Evidência esperada:

```text
Data/hora UTC:
Fonte da configuração:
Resultado sem expor segredos:
Responsável:
```

### Banco e recuperação

- [ ] Migrations em `db/migrations/` aplicadas antes do restart de produção.
- [ ] Usuário runtime do banco não depende de DDL em produção.
- [ ] Backup regular configurado com `scripts/postgres_backup.py` ou rotina equivalente.
- [ ] Restore drill em staging validado com `scripts/postgres_restore_drill.py` ou rotina equivalente.
- [ ] Retenção dos dumps definida fora do diretório da aplicação.

Evidência esperada:

```text
Data/hora UTC:
Backup usado:
Destino de staging:
Resultado do restore:
Responsável:
```

### Monitoramento e incidentes

- [ ] `promtool check rules monitoring/prometheus/alerts.yml` passou.
- [ ] Prometheus ingere as métricas do alvo `lavpop-chatbot`.
- [ ] Alertas críticos chegam ao canal operacional.
- [ ] Runbook de DB e assinatura Meta está disponível para o responsável de plantão.
- [ ] Logs em produção seguem `docs/LOGGING_AND_DATA_RETENTION_POLICY.md`.

Evidência esperada:

```text
Data/hora UTC:
Prometheus/Alertmanager:
Canal de alerta:
Resultado:
Responsável:
```

## Próxima reavaliação

Reavaliar este documento após:

- mudança de domínio, proxy, secrets ou topologia de rede;
- alteração de schema;
- incidente SEV-1/SEV-2;
- aumento relevante de volume;
- implementação de deploy automático substituindo o deploy manual supervisionado atual.
