# Política de Logs, PII e Retenção

## Objetivo

Reduzir exposição de dados pessoais em produção e definir retenção operacional
mínima para conversas, mensagens e deduplicação de webhooks.

## Regras de log em produção

- `APP_DEBUG_LOG_MODE` deve permanecer `false` em `APP_ENV=prod|production`.
- Logs não devem registrar telefone em claro; usar apenas `phone_hash`.
- Logs não devem registrar payload bruto do webhook em produção.
- Logs podem registrar `event_key`, tipo de mensagem, `payload_hash` truncado,
  origem da resposta, regra/intenção e resultado de processamento.
- Previews de texto devem ser curtos e usados apenas para diagnóstico; não
  devem substituir consulta auditada ao banco quando houver investigação.
- Secrets, tokens, headers de assinatura e `DATABASE_URL` nunca devem aparecer
  em logs.

## Dados persistidos

As tabelas abaixo podem conter dados pessoais ou conteúdo de conversa:

- `chatbot.log_conversas`
- `chatbot.mensagens`
- `chatbot.contexto_cliente`

As tabelas abaixo são operacionais e devem manter retenção curta:

- `chatbot.webhook_event_dedup`

## Retenção recomendada

- `chatbot.webhook_event_dedup`: 30 dias.
- `chatbot.mensagens`: 180 dias.
- `chatbot.log_conversas`: 180 dias.
- `chatbot.contexto_cliente`: manter enquanto houver relacionamento ativo;
  anonimizar ou remover registros inativos conforme política comercial/LGPD.
- Backups: manter em storage externo ao diretório da aplicação, com retenção
  compatível com a política da operação e acesso restrito.

## Rotina operacional

- Executar limpeza de dados antigos em janela controlada e com backup recente.
- Validar contagem de linhas antes/depois da limpeza.
- Registrar data, operador, critérios usados e volume removido.
- Nunca executar limpeza diretamente em produção sem teste prévio em staging
  quando houver mudança no critério.
- Preferir `scripts/postgres_retention_cleanup.py` em modo dry-run antes de
  executar remoção real (`--apply`).

## Consultas de referência

Exemplos para staging ou execução controlada:

```sql
SELECT COUNT(*) FROM chatbot.webhook_event_dedup
 WHERE processed_at < NOW() - INTERVAL '30 days';

SELECT COUNT(*) FROM chatbot.mensagens
 WHERE created_at < NOW() - INTERVAL '180 days';

SELECT COUNT(*) FROM chatbot.log_conversas
 WHERE created_at < NOW() - INTERVAL '180 days';
```

Remoção deve ser feita em lotes quando houver volume alto:

```sql
DELETE FROM chatbot.webhook_event_dedup
 WHERE processed_at < NOW() - INTERVAL '30 days';
```

## Critério de aceite para produção controlada

- O baseline de produção bloqueia `APP_DEBUG_LOG_MODE=true`.
- Amostras recentes de log não mostram telefone, tokens, secrets ou payload
  bruto.
- Existe responsável definido para executar ou automatizar retenção.
- Restore drill foi validado antes de qualquer limpeza destrutiva.
