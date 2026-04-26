# Roadmap de PRs Temáticos

## Objetivo

Manter as próximas melhorias em **PRs independentes, partindo sempre de `main`**. Cada PR deve carregar um único tema principal, com validação própria e sem misturar mudanças de áreas diferentes.

## Sequência recomendada

### 1. Segurança e LGPD

- Redaction consistente de logs e previews.
- Política de retenção de mensagens, contexto e deduplicação.
- Revisão de exposição de dados sensíveis em debug, métricas e operadores.
- Testes que garantam ausência de payload bruto e de telefone em claro em produção.

### 2. Governança de deploy

- `preflight` padronizado.
- Runbook de operação manual, smoke, backup e rollback.
- Checklist de produção e validação de borda.
- Documentação de porta, systemd e restart seguro.

### 3. Arquitetura do webhook

- Separar parsing, roteamento, persistência e envio.
- Reduzir responsabilidade de `app/main.py`.
- Fortalecer testes de contrato para payloads reais da Meta.
- Preparar caminho para métricas mais granulares por origem e falha.

## Regras para cada PR

- Partir do `main` mais recente.
- Conter apenas um tema principal.
- Trazer teste(s) que provem a mudança.
- Passar por `make lint`, `make compile` e `make test`.
- Evitar misturar refactor estrutural com mudança de comportamento funcional.

## Critério de aceite

- A fila de melhorias fica sempre rastreável por tema.
- Revisões ficam menores e mais previsíveis.
- O rollback de cada PR continua simples, porque o escopo é fechado.
