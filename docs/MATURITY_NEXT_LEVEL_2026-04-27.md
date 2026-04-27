# Próximo nível de maturidade (27/04/2026)

## Resumo executivo

Status atual: o projeto já opera com boa base para **produção controlada**, com sinais fortes de maturidade em segurança de webhook, confiabilidade operacional inicial e suíte de testes robusta.

Para subir de nível (de "produção controlada" para "operação estável em escala"), os próximos passos devem focar em cinco eixos:

1. **Arquitetura de processamento assíncrono** para desacoplar webhook de envio/resolução de resposta.
2. **Maturidade de dados e migrations** com governança de schema e rollback previsível.
3. **SRE/Operação** com SLOs formais, dashboards e gestão de incidentes orientada por erro.
4. **Segurança/LGPD** com redução adicional de exposição de PII e gestão centralizada de segredos.
5. **Produto e eficiência operacional** com painel de operação mais forte e métricas de negócio.

---

## Evidências observadas no estado atual

- Baseline estrito de segurança em produção já está codificado (`APP_ENV=prod`, assinatura HMAC obrigatória, debug proibido em produção).  
- Observabilidade já existe com métricas Prometheus e health endpoints, incluindo contadores de erros por tipo e latência de webhook.  
- Há deduplicação/idempotência de webhook e validação de schema mínimo/obrigatório no banco.  
- A suíte de testes está ampla para o estágio atual (101 testes passando localmente neste ciclo).  
- A própria documentação já posiciona o momento como "go-live controlado", com itens de evolução explícitos para próximos ciclos.

---

## Ajuste de estratégia para baixo volume (até ~10 conversas/semana)

Para este contexto específico, **faz sentido validar parte relevante em produção**, desde que em
formato de produção controlada (com guardrails) e não como “teste livre” em horário integral.

### Recomendação prática

1. Manter um pequeno conjunto de números internos para teste (whitelist operacional).
2. Executar janelas curtas de experimento (ex.: 30–60 minutos) em horários de baixo risco.
3. Ativar checklist pré-teste: healths, DB pronto, assinatura Meta válida, backup recente.
4. Coletar evidências objetivas durante cada janela:
   - latência de processamento;
   - taxa de erro;
   - taxa de handoff humano;
   - falhas de envio Meta.
5. Encerrar a janela e registrar decisão: manter, reverter ou corrigir antes da próxima rodada.

### Limites importantes

- Mesmo com baixo volume, **não** pular testes mínimos em staging/local para mudanças de schema,
  autenticação de webhook e fluxo de banco.
- Mudanças de migration continuam exigindo validação prévia e plano de rollback.
- Produção deve ser usada para validação incremental de comportamento real, não para descobrir
  falhas críticas de baseline.

---

## Backlog recomendado para o próximo nível (priorizado)

## P0 (0–2 semanas) — estabilização operacional de curto prazo

### 1) Definir e operar SLOs formais

**Objetivo:** trocar monitoramento reativo por metas explícitas de confiabilidade.

**Implementar:**
- SLO de disponibilidade do webhook (ex.: 99,9%).
- SLO de latência de processamento (ex.: p95 < 1,5s no caminho síncrono atual).
- SLO de erro de processamento por tipo.
- Error budget mensal com ritual semanal de revisão.

**Entregáveis:**
- Documento `docs/SLOs.md`.
- Dashboard com p50/p95/p99 + taxa de erro + deduplicação.
- Alerta por burn-rate (rápido e lento).

### 2) Fortalecer controle de capacidade do webhook

**Objetivo:** reduzir risco de saturação em picos/reentregas.

**Implementar:**
- Manter rate limit de borda como primeira camada e revisar limites internos por ambiente.
- Medir saturação de pool de DB e tempo de fila lógico do processamento.
- Definir limite de throughput suportado por instância.

**Entregáveis:**
- Teste de carga básico com cenários de pico e relatório de capacidade.
- Runbook de degradação graciosa (ex.: priorizar registro e reduzir respostas custosas).

### 3) Hardening imediato de segredos e acesso operacional

**Objetivo:** reduzir risco operacional de credenciais e superfícies internas.

**Implementar:**
- Secret manager para produção (não depender de `.env` em runtime).
- Rotação programada de tokens/segredos da Meta e DB.
- Revisão de rede interna para `/metrics`, `/health/*` e `/operator`.

**Entregáveis:**
- Inventário de segredos + política de rotação.
- Evidência de rotação sem downtime relevante.

---

## P1 (2–6 semanas) — salto arquitetural e governança

### 4) Migrar webhook para arquitetura assíncrona (fila)

**Objetivo:** aumentar resiliência e reduzir acoplamento do caminho crítico.

**Implementar:**
- `POST /webhook/meta` faz ingestão + validação + persistência mínima e retorna rápido.
- Worker assíncrono processa roteamento, consulta de regras/IA e envio à Meta.
- Estratégia de retry com backoff e DLQ para falhas persistentes.

**Impacto esperado:**
- Menor latência percebida no webhook.
- Maior tolerância a indisponibilidade temporária de dependências.
- Diagnóstico mais claro entre erro de ingestão vs erro de processamento.

### 5) Evoluir migrations para fluxo estritamente versionado

**Objetivo:** tornar mudanças de schema previsíveis e auditáveis.

**Implementar:**
- Consolidar padrão único de migrations versionadas e checklist de rollback.
- Gate de CI para validar migração + downgrade em ambiente efêmero.
- Política clara de compatibilidade entre versão da app e versão de schema.

### 6) Logs e rastreabilidade ponta a ponta

**Objetivo:** acelerar RCA e reduzir MTTR.

**Implementar:**
- Padronizar logs estruturados (JSON) com `event_key`, `message_id`, `phone_hash`, `trace_id`.
- Propagação de correlação entre webhook, DB e envio Meta.
- Definir retenção por criticidade (operacional vs auditoria).

---

## P2 (6–12 semanas) — escala, compliance e produto

### 7) LGPD/data governance avançada

- Política de minimização de dados por tabela/coluna.
- Criptografia de campos sensíveis em repouso quando aplicável.
- Procedimento formal para anonimização e deleção sob demanda.

### 8) Painel operacional e fluxo humano

- Evoluir `/operator` para operação segura com RBAC simples e trilha de auditoria.
- Métricas de atendimento humano (tempo de primeira resposta, tempo de resolução, taxa de handoff).

### 9) Métricas de negócio e experimentação

- Funil por intenção/opção de menu.
- Taxa de resolução sem handoff humano.
- Taxa de reengajamento após mensagem de inatividade.

---

## Plano de execução sugerido

### Sprint A (semana 1–2)
- SLOs + dashboards + alertas burn-rate.
- Teste de carga inicial e baseline de capacidade.
- Secret manager e política de rotação.

### Sprint B (semana 3–4)
- Desenho técnico da fila + protótipo de worker.
- Contratos de evento e semântica de retry/idempotência.

### Sprint C (semana 5–6)
- Migração gradual do fluxo síncrono para assíncrono.
- Observabilidade ponta a ponta com correlação.

### Sprint D (semana 7–8)
- Endurecimento de migrations + rollback testado.
- Revisão LGPD e auditoria operacional do painel humano.

---

## Indicadores de que o “próximo nível” foi alcançado

Considere que o projeto mudou de patamar quando, por pelo menos 30 dias:

- SLOs estão definidos, monitorados e dentro do alvo.
- Incidentes têm TTD/MTTR medidos e em queda.
- Webhook responde rápido mesmo sob pico, com processamento desacoplado.
- Migrations e rollback são executáveis e repetíveis em CI/staging.
- Controles de acesso e segredos em produção passam auditoria interna.

---

## Conclusão

O projeto já fez o difícil da base (segurança de webhook, idempotência, testes e governança inicial). O salto de maturidade agora é menos sobre “novas features” e mais sobre **desacoplamento arquitetural, disciplina operacional e governança de dados**.

Se o time executar P0 + P1 nesta ordem, a tendência é reduzir risco operacional rapidamente e abrir espaço para escalar volume com previsibilidade.

## Anexo operacional semanal

Para execução recorrente das janelas de validação em produção controlada, usar:

- `docs/PRODUCTION_TEST_WINDOW_WEEKLY_RUNBOOK.md`
