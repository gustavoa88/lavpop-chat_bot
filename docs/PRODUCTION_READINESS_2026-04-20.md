# Validação de Produção (20/04/2026)

## Escopo da validação

Validação técnica do chatbot FastAPI + PostgreSQL com foco em prontidão para produção:

1. **Confiabilidade** (testes automatizados e idempotência)
2. **Segurança** (assinatura de webhook, baseline em produção)
3. **Operabilidade** (health checks, métricas e logs)
4. **Dados e persistência** (pool, readiness, consistência)
5. **Governança de deploy** (gates e checklist de release)

## Evidências executadas

- `pytest -q` → **48 passed, 3 skipped**
- `pytest -m integration -q` → **3 skipped** (sem DSN de Postgres de integração no ambiente)
- `python -m compileall app tests` → **sucesso**

## Diagnóstico objetivo

### Status geral

O projeto está **bem encaminhado para produção controlada (beta/early production)**. Já existem mecanismos importantes de robustez:

- validação de assinatura HMAC no webhook (com modo estrito para produção);
- deduplicação de eventos do webhook para reduzir respostas duplicadas;
- endpoints de liveness/readiness/db-health;
- endpoint `/metrics` em formato Prometheus;
- suíte de testes unitários sólida para o estágio atual.

### Risco atual para produção plena

O principal risco não é funcional, e sim de **governança operacional**:

- integração com Postgres real não está validada neste ambiente (testes marcados como integration ficaram skipped);
- faltam políticas explícitas de proteção de borda (rate limit, WAF/reverse proxy e controle de acesso para observabilidade);
- faltam gates de release mais rígidos (ex.: cobertura mínima, integração obrigatória em CI para todo merge em branch protegida).

## Ajustes recomendados antes de produção (prioridade)

## P0 — Obrigatórios para go-live seguro

1. **Executar e tornar obrigatório o teste de integração com Postgres real no pipeline de release**
   - Definir `TEST_POSTGRES_DSN` no CI e bloquear deploy se `pytest -m integration` falhar.
   - Motivação: reduzir risco de regressões em pool/conexão/DDL e idempotência real.

2. **Forçar baseline de segurança estrito em produção**
   - Em produção: `APP_ENV=prod`, `META_VALIDATE_SIGNATURE=true`, `META_REQUIRE_APP_SECRET=true` e `META_APP_SECRET` presente.
   - Motivação: impedir processamento de webhook sem validação criptográfica.

3. **Restringir acesso a endpoints operacionais (`/metrics`, `/health/*`) em rede interna ou via autenticação de borda**
   - Hoje esses endpoints são úteis, mas podem expor telemetria para externos.

## P1 — Fortemente recomendados (primeira iteração pós-go-live)

4. **Adicionar rate limiting e proteção de abuso no webhook**
   - Ex.: limite por IP/origem no ingress/reverse proxy.
   - Motivação: proteger disponibilidade e custo de processamento.

5. **Padronizar logs estruturados com correlação**
   - Incluir `event_key`, `message_id`, `phone_hash`, `intent`, `source` e tempo de processamento por evento.
   - Motivação: acelerar diagnóstico de incidentes.

6. **Definir SLOs e alertas operacionais**
   - Erro de processamento, indisponibilidade de DB, latência de webhook e taxa de deduplicação.

## P2 — Evolução de maturidade

7. **Governança de migrations**
   - Introduzir ferramenta versionada (ex.: Alembic/Flyway) para histórico de schema e rollback.

8. **Hardening de segredo e compliance operacional**
   - Secret manager (em vez de `.env` em runtime de produção), rotação periódica e política de expiração.

9. **Teste de carga e plano de capacidade**
   - Simular picos de webhook e definir limites de pool/CPU/memória por ambiente.

## Checklist mínimo de produção (resumo)

- [x] CI de release executa `pytest -q` e `pytest -m integration -q` com Postgres real.
- [x] Deploy bloqueado por workflow (`Deploy release`) se integração falhar ou baseline de segurança estiver fora do padrão.
- [x] `/metrics` e `/health/*` acessíveis somente internamente.
- [x] Runbook com procedimentos para indisponibilidade de DB e falha de autenticação na Meta.
- [x] Alertas configurados para disponibilidade e erro de processamento.

## Conclusão

**Recomendação:** ainda **não** classificar como “produção plena” sem os itens P0.  
Com P0 implementado e validado em CI + ambiente staging, o sistema fica apto para entrada em produção com risco controlado.

## Revalidação (20/04/2026 — ciclo 2)

Reexecução completa dos checks locais após ajustes de CI:

- `pytest -q` → **48 passed, 3 skipped**
- `pytest -m integration -q` → **3 skipped** (ambiente local sem `TEST_POSTGRES_DSN`)
- `python -m compileall app tests` → **sucesso**

### Observação

O pipeline já está configurado para executar, no gate de release, a suíte unitária completa (`pytest -q`) e os testes de integração com PostgreSQL (`pytest -m integration -q`) usando service `postgres` no GitHub Actions.

O bloqueio de deploy já está implementado no workflow:

- Job `Deploy release (blocked by integration gate)` depende de `tests` + `Integration tests (release gate)` (`needs`).
- O deploy é abortado se baseline estrito de segurança não estiver conforme (`APP_ENV` prod/production, assinatura validada e App Secret obrigatório).

Para completar a governança de merge em `main`, ainda recomenda-se no GitHub (nível de repositório):

- Branch protection/ruleset exigindo o check `Integration tests (release gate)` para `main`;
- Bloqueio de merge enquanto esse check estiver falhando ou pendente.

## Verificação operacional final — branch protection/ruleset (GitHub)

Status da validação nesta revisão:

- [ ] Confirmar no GitHub (Settings → Branches/Rulesets) que `main` exige o check `Integration tests (release gate)`.
- [ ] Confirmar bloqueio de merge com checks pendentes/falhando para PRs em `main`.
- [ ] Confirmar exigência de branch atualizada com status checks antes do merge (strict mode/rebase requirement).

> Observação: esta confirmação depende de acesso administrativo ao repositório no GitHub.

## Alertas operacionais configurados

As regras mínimas para disponibilidade e erro de processamento foram registradas em:

- `monitoring/prometheus/alerts.yml`
- `docs/ALERTING_SETUP_2026-04-20.md`

## Runbook operacional — indisponibilidade de DB e falha de autenticação Meta

### Objetivo

Fornecer um procedimento único, rápido e auditável para dois incidentes de alto impacto:

1. indisponibilidade de PostgreSQL;
2. rejeição de autenticação/assinatura em webhook da Meta.

### Pré-requisitos operacionais

- Dashboard com métricas de erro/latência do webhook e de saúde de banco.
- Acesso a logs estruturados da API com filtros por `event_key`, `message_id` e status HTTP.
- Acesso seguro aos segredos: `DATABASE_URL`, `META_APP_SECRET`, `META_VERIFY_TOKEN`.
- Canal de incidente definido (ex.: Slack/Teams + paging).

### Severidade e gatilhos

#### SEV-1 (crítico)

- webhook indisponível para maioria das requisições por mais de **5 minutos**;
- falhas 5xx contínuas por indisponibilidade do DB;
- assinatura Meta rejeitada em **100%** dos eventos por mais de **5 minutos**.

#### SEV-2 (alto)

- aumento consistente de erros de DB com degradação parcial;
- aumento de 401/403 de assinatura com queda parcial de processamento.

### Incidente A — indisponibilidade de DB (PostgreSQL)

#### Sintomas comuns

- falhas em `/health/readiness` ou `/health/db-health`;
- aumento de 5xx no webhook;
- timeouts de conexão/pool esgotado.

#### Procedimento (primeiros 15 minutos)

1. **Abrir incidente e classificar severidade** (SEV-1/SEV-2).
2. **Confirmar escopo**:
   - validar `/health/live`, `/health/readiness`, `/health/db-health`;
   - verificar taxa de erro no webhook e latência p95/p99.
3. **Checar conectividade e credenciais**:
   - DNS/rota para host do Postgres;
   - validade da `DATABASE_URL` (sem rotação incompleta).
4. **Avaliar saturação de pool**:
   - conexões ativas vs. limite;
   - queries longas/bloqueios.
5. **Mitigação imediata**:
   - reduzir tráfego na borda (rate limit temporário) se houver tempestade de eventos;
   - reiniciar somente pods/instâncias afetadas se houver leak de conexão;
   - escalar vertical/horizontalmente conforme playbook da plataforma.
6. **Escalonar para time de dados/cloud** se indisponibilidade externa ao app.

#### Critérios de recuperação

- `/health/readiness` e `/health/db-health` estáveis por **15 minutos**;
- erro do webhook dentro do baseline;
- sem crescimento anormal de backlog/fila.

#### Ações pós-incidente

- documentar causa raiz (RCA) em até 48h;
- registrar métricas: tempo de detecção (TTD), mitigação (TTM) e recuperação (TTR);
- criar ação corretiva (ex.: ajuste de pool, timeout, índice, capacidade do cluster).

### Incidente B — falha de autenticação/assinatura Meta

#### Sintomas comuns

- respostas 401/403 no webhook;
- logs de “invalid signature” ou “app secret missing/required”;
- queda brusca no processamento de mensagens entrantes.

#### Procedimento (primeiros 15 minutos)

1. **Abrir incidente e classificar severidade**.
2. **Validar baseline de segurança em runtime**:
   - `APP_ENV=prod` (ou `production`);
   - `META_VALIDATE_SIGNATURE=true`;
   - `META_REQUIRE_APP_SECRET=true`;
   - `META_APP_SECRET` definido.
3. **Conferir integridade de segredo e rotação**:
   - verificar se houve rotação recente no secret manager;
   - confirmar sincronização do segredo entre ambiente e app.
4. **Validar endpoint e headers recebidos**:
   - confirmar presença do header de assinatura esperado;
   - revisar se proxy/gateway não removeu headers.
5. **Mitigação imediata**:
   - corrigir segredo e redeploy controlado;
   - se incidente for causado por configuração de borda, aplicar rollback rápido da mudança.
6. **Revalidar com evento real/sintético** para confirmar aceitação da assinatura.

#### Critérios de recuperação

- taxa de 401/403 de autenticação volta ao baseline por **15 minutos**;
- eventos voltam a ser processados com sucesso;
- sem backlog crescente na entrada de webhook.

#### Ações pós-incidente

- registrar RCA com foco em gestão de segredo/configuração;
- implementar guarda adicional no deploy (validação de variáveis críticas);
- avaliar dupla validação de configuração antes do go-live (checklist + smoke test).

### Comunicação durante incidentes

- **T+0–5 min:** alerta no canal de incidente com severidade, impacto e owner técnico;
- **T+15 min:** status update com hipótese principal e mitigação em andamento;
- **A cada 30 min (SEV-1):** atualização executiva curta;
- **Encerramento:** resumo do impacto, janela temporal, causa raiz provável e próximos passos.

### Evidências mínimas a coletar

- trecho de logs com erro e timestamp UTC;
- print/export de métricas de erro/latência;
- configuração efetiva (sem expor segredo) das variáveis críticas;
- timeline do incidente (detecção → mitigação → recuperação).
