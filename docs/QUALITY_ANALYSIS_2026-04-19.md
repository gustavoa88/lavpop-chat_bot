# Análise de Qualidade do Projeto (19/04/2026)

## Resumo executivo

O projeto está bem estruturado para um **MVP funcional** (FastAPI + PostgreSQL + fallback de IA), mas ainda depende fortemente de validação manual.

**Próximo passo recomendado (maior impacto):** implementar uma base de **testes automatizados + CI** para proteger os fluxos críticos (webhook, regras, fallback IA e persistência).

## Diagnóstico técnico (estado atual)

### Pontos fortes
- Arquitetura simples e clara (`config`, `db`, `services`, `main`), facilitando manutenção incremental.
- Persistência de contexto e log de conversas já modeladas no banco.
- Estratégias de resiliência iniciais:
  - retry para OpenAI;
  - retry para envio Meta;
  - bloqueio temporário após erro de autenticação Meta.
- Webhooks de verificação e recebimento já implementados.

### Lacunas que impactam qualidade em produção
- Não há suíte de testes automatizados (unitários/integração).
- Não há pipeline de CI para impedir regressões antes de merge/deploy.
- Segurança de webhook ainda sem validação criptográfica de assinatura.
- Healthcheck não valida conectividade real com banco/dependências.
- Observabilidade ainda limitada (sem métricas estruturadas de sucesso/erro/latência).

## Próximo passo único para elevar a qualidade

## 1) Criar cobertura mínima de testes + CI (prioridade máxima)

### Objetivo
Garantir que mudanças no código não quebrem os fluxos essenciais do bot.

### Escopo mínimo (primeiro ciclo)
- **Testes unitários (services):**
  - normalização de texto/telefone;
  - match de regra por `palavras_chave`;
  - classificação de intenção;
  - fallback quando OpenAI indisponível.
- **Testes de webhook (FastAPI TestClient):**
  - validação de `GET /webhook/meta` com token correto/incorreto;
  - `POST /webhook/meta` com payload válido e payload parcial;
  - garantia de idempotência básica em mensagens sem texto.
- **Testes de integração (DB):**
  - `save_log` grava corretamente;
  - `save_context` incrementa `total_interacoes` no `ON CONFLICT`.
- **CI (GitHub Actions):**
  - instalar dependências;
  - executar testes;
  - falhar PR em caso de regressão.

### Meta de saída (Definition of Done)
- Pipeline de CI executando em todo PR.
- Cobertura inicial >= 60% em `app/services.py` e `app/main.py`.
- Pelo menos 1 teste cobrindo cada rota de webhook e cada caminho de decisão do `answer_message`.

## Próximos passos após esse ciclo
1. Assinatura HMAC/validação de origem no webhook Meta.
2. Endpoint de health/readiness com verificação real de DB.
3. Métricas e logs estruturados (latência, taxa de erro por origem `banco` vs `ia`).
4. Estratégia de deduplicação de mensagens para evitar respostas repetidas.
