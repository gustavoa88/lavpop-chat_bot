# Alerting operacional (20/04/2026)

Este documento formaliza os alertas mínimos de produção para disponibilidade e erro de processamento.

## Arquivo de regras

As regras Prometheus estão em:

- `monitoring/prometheus/alerts.yml`

## Alertas configurados

### Disponibilidade

1. `LavpopChatbotUnavailable` (critical)
   - dispara quando `up{job="lavpop-chatbot"} == 0` por 3 minutos;
   - indica indisponibilidade da API/alvo no scrape.

2. `LavpopChatbotDatabaseDown` (critical)
   - dispara quando `chatbot_database_ready == 0` por 2 minutos;
   - indica indisponibilidade de banco observada pela própria API.

### Erro de processamento

3. `LavpopChatbotProcessingErrorRateHigh` (warning)
   - calcula `rate(chatbot_message_processing_errors_total) / rate(chatbot_webhook_requests_total)` em janela de 5 minutos;
   - dispara acima de 5% por 10 minutos.

4. `LavpopChatbotSignatureFailuresHigh` (critical)
   - dispara quando há falhas sustentadas em `chatbot_webhook_signature_failures_total`;
   - indica segredo incorreto, assinatura ausente ou tentativa de spoofing.

5. `LavpopChatbotWebhookLatencyP95High` (warning)
   - usa `histogram_quantile(0.95, rate(chatbot_webhook_processing_duration_seconds_bucket[5m]))`;
   - dispara acima de 2 segundos por 15 minutos.

## Integração com Prometheus

Exemplo mínimo de inclusão do arquivo no `prometheus.yml`:

```yaml
rule_files:
  - /etc/prometheus/alerts/lavpop-chatbot-alerts.yml
```

Copie `monitoring/prometheus/alerts.yml` para esse caminho (ou ajuste para o caminho padrão do seu ambiente).

## Encaminhamento para Alertmanager

Para cada alerta:
- `severity=critical` -> pager/on-call imediato.
- `severity=warning` -> canal técnico (Slack/Teams) com triagem em horário comercial.

## Verificação pós-configuração

1. Validar sintaxe:

```bash
promtool check rules monitoring/prometheus/alerts.yml
```

2. Confirmar ingestão das métricas:
- `chatbot_webhook_requests_total`
- `chatbot_message_processing_errors_total`
- `chatbot_webhook_signature_failures_total`
- `chatbot_database_ready`
- `chatbot_webhook_processing_duration_seconds_bucket`

3. Simular condição de erro (em staging) e verificar recebimento no canal correto.

## Observação

A regra de latência agora usa histogramas. Para SLOs ainda mais precisos, recomenda-se segmentar por tipo de evento em ciclo futuro.
