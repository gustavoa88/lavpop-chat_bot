# Próximo passo recomendado (29/04/2026)

## Contexto

A partir do estado atual do repositório e dos documentos estratégicos vigentes, o próximo passo de maior retorno é iniciar o **P0 de maturidade operacional com SLOs formais e alertas por error budget**.

## Por que este é o próximo passo

1. A base de produção controlada já existe (segurança de webhook, idempotência, observabilidade inicial e suíte de testes ampla).
2. O principal gargalo agora não é feature, mas previsibilidade operacional.
3. O plano de maturidade já prioriza explicitamente SLOs antes do salto arquitetural assíncrono.

## Escopo objetivo do próximo PR (tema único)

### Tema: SRE/Operação — SLOs e error budget

Entregáveis mínimos:
- Novo documento `docs/SLOs.md` com:
  - SLO de disponibilidade do webhook;
  - SLO de latência p95;
  - SLO de taxa de erro por tipo;
  - definição de error budget mensal.
- Atualização de `monitoring/prometheus/alerts.yml` com alertas de burn-rate (rápido e lento).
- Testes unitários de configuração para validar limites e flags de alerta/threshold.
- Runbook curto para ação em violação de SLO.

## Ordem prática sugerida (1 semana)

1. Definir metas iniciais realistas de SLO com dados atuais.
2. Instrumentar/confirmar métricas necessárias para disponibilidade, latência e erro.
3. Configurar regras de alerta por burn-rate em Prometheus.
4. Escrever runbook de resposta operacional.
5. Validar em janela de produção controlada.

## Critério de pronto

- SLOs documentados e versionados.
- Alertas ativos e testados.
- Ritual semanal de revisão de error budget definido.
- Evidência de pelo menos uma janela monitorada ponta a ponta.
