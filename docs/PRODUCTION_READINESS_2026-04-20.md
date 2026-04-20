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

- [ ] CI de release executa `pytest -q` e `pytest -m integration -q` com Postgres real.
- [x] Deploy bloqueado por workflow (`Deploy release`) se integração falhar ou baseline de segurança estiver fora do padrão.
- [ ] `/metrics` e `/health/*` acessíveis somente internamente.
- [ ] Runbook com procedimentos para indisponibilidade de DB e falha de autenticação na Meta.
- [ ] Alertas configurados para disponibilidade e erro de processamento.

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
