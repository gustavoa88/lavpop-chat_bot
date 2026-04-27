# Janela semanal de teste em produção (1 página)

> Objetivo: validar mudanças com segurança em **produção controlada** para baixo volume,
> com decisão clara de **GO / NO-GO** ao fim da janela.

## 1) Escopo da janela (preencher antes)

- **Data/hora (UTC):**
- **Responsável técnico:**
- **Responsável de negócio/operação:**
- **Mudança a validar (commit/PR):**
- **Hipótese do teste (o que precisa provar):**
- **Duração da janela:** 30–60 min
- **Canal de incidente:**
- **Plano de rollback:**

---

## 2) Checklist pré-janela (T-15 min)

Marque tudo antes de iniciar:

- [ ] `APP_ENV=prod|production`
- [ ] `META_VALIDATE_SIGNATURE=true`
- [ ] `META_REQUIRE_APP_SECRET=true`
- [ ] `APP_DEBUG_LOG_MODE=false`
- [ ] `/health/live` e `/health/ready` saudáveis em rede autorizada
- [ ] Métricas (`/metrics`) disponíveis para observação interna
- [ ] Backup recente confirmado
- [ ] Rollback testado/documentado para a versão anterior
- [ ] Lista de números de teste internos (whitelist) confirmada
- [ ] Alguém de plantão monitorando durante toda a janela

**Pré-condição:** se qualquer item acima falhar, **NO-GO imediato**.

---

## 3) Execução da janela (30–60 min)

### Passo A — Smoke funcional básico

- [ ] Enviar mensagem simples (`oi`) e validar resposta esperada
- [ ] Testar opção de menu (1–5) e validar roteamento
- [ ] Testar fallback (mensagem fora de regra)
- [ ] Validar handoff humano (quando aplicável)

### Passo B — Estabilidade operacional

Registrar medições do período:

- **Latência p95 webhook:**
- **Taxa de erro 5xx:**
- **Falhas de autenticação de assinatura:**
- **Falhas de envio Meta:**
- **Erros de banco/conexão:**

### Passo C — Segurança mínima

- [ ] Sem exposição pública indevida de `/metrics` e `/health/*`
- [ ] Sem logs com dados sensíveis em texto aberto
- [ ] Sem comportamento inesperado de autenticação/assinatura

---

## 4) Critérios de GO / NO-GO

## GO (pode manter a mudança)

- Fluxos críticos funcionaram sem erro bloqueante.
- Taxa de erro permaneceu dentro do baseline acordado da operação.
- Não houve incidente de segurança (assinatura, exposição de endpoint, segredo).
- Não houve necessidade de intervenção manual contínua para manter estabilidade.

## NO-GO (reverter/pausar)

- Qualquer falha em autenticação de assinatura por configuração incorreta.
- Aumento relevante de 5xx ou indisponibilidade de DB durante a janela.
- Falha em fluxo crítico (receber, rotear, responder, registrar).
- Exposição de endpoint operacional para origem não autorizada.
- Evidência de risco de dados sensíveis em logs.

**Regra prática:** na dúvida entre GO e NO-GO, escolher **NO-GO** e corrigir antes da próxima janela.

---

## 5) Encerramento e registro (T+10 min)

Preencher ao final:

- **Decisão final:** GO / NO-GO
- **Resumo executivo (3 linhas):**
- **Incidentes encontrados:**
- **Ações corretivas e responsáveis:**
- **Data da próxima janela:**

Anexos recomendados:
- link do dashboard do período;
- prints/export de métricas;
- commit/PR validado;
- evidência de rollback (se executado).
