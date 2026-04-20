# Revisão Crítica de Prontidão para Produção (20/04/2026)

## Resumo executivo (go/no-go)

**Recomendação atual: NO-GO para produção plena** até fechar os bloqueadores de segurança e operação abaixo.  
Para **produção controlada (beta com baixo volume)**, o sistema está próximo, mas ainda com riscos relevantes em exposição de dados operacionais e estabilidade sob carga.

### Scorecard de prontidão (0–5)

| Pilar | Nota | Situação | Comentário crítico |
|---|---:|---|---|
| Segurança de borda e webhook | 3.5 | Parcial | HMAC existe e baseline estrito em `prod`, mas ainda depende de configuração correta de proxy/rede e sem rate limiting no app. |
| Confiabilidade e testes | 4.0 | Bom | Suíte unitária forte (`55 passed`) e gate de integração no CI para release, porém integração local não validada por padrão sem DSN. |
| Observabilidade e SRE | 3.0 | Parcial | Métricas e healthchecks existem, mas faltam tracing, correlação sistemática e SLO formal no código/pipeline. |
| Dados e persistência | 3.5 | Parcial | Pool + healthcheck + idempotência implementados; falta governança de migrations versionadas e política de retenção. |
| Resiliência de integração externa | 3.0 | Parcial | Retries e backoff existem, mas sem circuit breaker robusto por categoria de falha e sem fila assíncrona para desacoplamento. |
| Governança de release | 3.5 | Parcial | CI com gates relevantes; ainda depende de branch protection no GitHub e processo de incident response disciplinado. |

**Nota global estimada: 3.4/5.0**

---

## Evidências verificadas nesta revisão

- Testes unitários: `pytest -q` → **55 passed, 3 skipped**.
- Testes de integração: `pytest -m integration -q` → **3 skipped** (sem `TEST_POSTGRES_DSN` no ambiente local).
- Sanidade de build Python: `python -m compileall app tests` → **sucesso**.
- Revisão de implementação de webhook, segurança e observabilidade em:
  - `app/main.py`
  - `app/services.py`
  - `app/db.py`
  - `app/config.py`
  - `.github/workflows/ci.yml`

---

## Análise crítica aprofundada

## 1) Segurança

### Pontos fortes

1. **Validação de assinatura HMAC do webhook** com comparação segura (`hmac.compare_digest`) e rejeição 403 para assinatura inválida.
2. **Baseline fail-fast para produção**: em `APP_ENV=prod|production`, aplicação exige modo estrito (`META_REQUIRE_APP_SECRET=true`) e pode falhar na inicialização quando necessário.
3. **Bloqueio de endpoints operacionais por origem interna**, com suporte a proxy confiável via CIDR.

### Riscos reais (críticos)

1. **Modelo de confiança em IP/proxy pode ser mal configurado**: se `TRUST_PROXY_HEADERS` e CIDRs forem configurados incorretamente, há risco de interpretar origem externa como interna.
2. **Sem proteção anti-abuso explícita no app**: webhook não aplica rate limit local; depende 100% da borda (ingress/WAF/API gateway).
3. **Logs podem carregar payload bruto do webhook** em nível info em alguns fluxos; isso pode incluir dados pessoais que merecem política de minimização/mascaramento.

### Decisão deste pilar

- **Go condicionado** para beta privado.
- **No-go para escala pública** sem hardening de borda + revisão LGPD de logs.

---

## 2) Confiabilidade e robustez funcional

### Pontos fortes

1. **Idempotência por evento** com tabela dedicada e `ON CONFLICT DO NOTHING`.
2. **Fallbacks controlados**: menu interativo com fallback para texto, IA com retry exponencial e resposta degradada.
3. **Tratamento tolerante de falhas por evento** no loop do webhook (erro em uma mensagem não derruba o lote inteiro).

### Riscos reais

1. **Sem fila assíncrona**: processamento síncrono dentro do request de webhook aumenta risco de timeout sob pico.
2. **Watcher de inatividade em thread no processo da API**: funcional, mas frágil para múltiplas réplicas (pode duplicar ações sem coordenação distribuída).
3. **Retorno HTTP sempre `{"status":"ok"}` após parse/loop** (com erro por item apenas em log) pode dificultar feedback operacional fino por webhook.

### Decisão deste pilar

- **Go para tráfego moderado**.
- **No-go para alto volume** antes de desacoplar ingestão/processamento.

---

## 3) Banco de dados e governança de schema

### Pontos fortes

1. Pool de conexões (`ThreadedConnectionPool`) com healthcheck de readiness e latência.
2. Provisionamento mínimo automático para deduplicação, reduzindo risco de duplicidade em bootstrap incompleto.

### Riscos reais

1. **Ausência de migrações versionadas formais** (Alembic/Flyway): risco elevado de drift entre ambientes e rollback inconsistente.
2. **Modo compatibilidade silencioso em falhas DDL**: app segue operando com warnings mesmo sem garantias completas de idempotência/estrutura.
3. **Sem evidência de política de retenção/arquivamento** para logs de conversa e dedup (crescimento contínuo).

### Decisão deste pilar

- **Go com supervisão** no curto prazo.
- **No-go para compliance e operação de longo prazo** sem migrations e data lifecycle.

---

## 4) Observabilidade, alertas e operação

### Pontos fortes

1. Endpoints de `live`, `ready`, `db` e `/metrics` já disponíveis.
2. Métricas básicas de webhook, duplicidade, erros e latência já publicadas.
3. Regras de alerta Prometheus e runbook operacional já documentados no repositório.

### Riscos reais

1. **Sem tracing distribuído** (OpenTelemetry ou equivalente) para rastrear jornada completa de mensagem.
2. **Sem correlação obrigatória padronizada** no log em todas as etapas (event_key/message_id em 100% dos logs relevantes).
3. **Sem SLO formal codificado** em dashboard/alerta (erro, latência p95/p99, disponibilidade alvo).

### Decisão deste pilar

- **Go para operação básica**.
- **No-go para operação madura 24x7** sem SLO+tracing.

---

## 5) Pipeline de release e governança

### Pontos fortes

1. CI executa testes unitários em qualquer branch.
2. Gate de integração com PostgreSQL para PR->`main`, `main` e tags `v*`.
3. Job de deploy bloqueia release se baseline de segurança (secrets) não estiver estrito.

### Riscos reais

1. **Dependência de branch protection externo ao YAML**: se não estiver ativado no GitHub, alguém pode burlar o gate por merge indevido.
2. **Sem verificação automática de cobertura mínima e quality gates estáticos** (ex.: lint/security scan).
3. **Deploy step ainda placeholder**: risco de gap entre validação e execução real de rollout.

### Decisão deste pilar

- **Go para processo inicial**.
- **No-go para governança forte** até fechar proteção de branch e endurecer gates.

---

## Bloqueadores para “produção plena” (P0)

1. **Rate limiting/WAF efetivo na borda do webhook**, com evidência em ambiente de staging.
2. **Branch protection obrigatório em `main`** exigindo check `Integration tests (release gate)` e bloqueio com status pendente/falho.
3. **Política de logs e PII**: reduzir payload bruto, mascarar dados sensíveis e definir retenção.
4. **Migrações versionadas** com rollback testado.
5. **Teste de carga básico com critérios de aceite** (latência, taxa de erro, consumo de conexão DB).

---

## Plano sugerido de entrada em produção

### Fase 1 (1–3 dias) — hardening mínimo

- Aplicar rate limit no ingress/API gateway.
- Ativar/validar branch protection em `main`.
- Revisar logs para mascaramento e remover payloads sensíveis.

### Fase 2 (3–7 dias) — robustez operacional

- Introduzir migrations versionadas.
- Formalizar SLO/SLI (latência, erro, disponibilidade) e alertas com limiares objetivos.
- Rodar teste de carga com cenário de reentrega/duplicidade.

### Fase 3 (7–14 dias) — escala e resiliência

- Desacoplar processamento de webhook (fila + worker).
- Implementar tracing distribuído.
- Definir estratégia de capacity planning por ambiente.

---

## Veredito final

Hoje, o projeto já tem uma **base técnica sólida** para um rollout controlado, mas ainda não atende plenamente o padrão de **produção madura** para escala previsível.  
Com fechamento dos P0 acima, a recomendação muda de **NO-GO** para **GO** com risco operacional aceitável.
