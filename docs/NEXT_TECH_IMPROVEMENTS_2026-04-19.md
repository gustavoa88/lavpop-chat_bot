# Próximas melhorias técnicas (reavaliação em 19/04/2026)

## Diagnóstico rápido do estado atual

Com base no código e na suíte de testes atual:
- O projeto já possui cobertura útil para webhook, HMAC, serviços centrais e deduplicação.
- Há observabilidade inicial (healths + `/metrics`) e idempotência por evento.
- O fluxo de atendimento mistura parsing de payload, lógica de domínio e envio HTTP em pontos centrais, o que dificulta evolução e testes de integração fim-a-fim.

## Melhoria aplicada nesta rodada

- Corrigido bug em produção potencial no webhook de `interactive.button_reply`: faltava importar `INTERACTIVE_MENU_ID_TO_OPTION` em `app/main.py`, o que causava `NameError` e descarte silencioso da mensagem com log de erro.
- Reduzida ambiguidade no parser de opções de menu em `services.py`: removida duplicação de função e ajustado mapeamento de `"atendimento"` para opção humana.
- Adicionado teste de regressão para garantir que `"Atendimento"` direciona para `menu_opcao_5`.

## Backlog técnico priorizado (próximo ciclo)

1. **Separar orquestração do webhook em camadas explícitas**
   - Extrair parsing do payload Meta para um módulo próprio (`app/webhook_parser.py`).
   - Extrair idempotência/event key para serviço dedicado.
   - Benefício: reduzir complexidade ciclomática de `app/main.py` e facilitar testes unitários puros.

2. **Instrumentação de métricas por tipo de origem de resposta**
   - Adicionar contadores por fonte (`menu`, `banco`, `ia`) e por tipo de falha.
   - Benefício: decisões de produto e tuning de base de FAQ guiadas por dados reais.

3. **Testes de contrato do payload Meta**
   - Criar casos cobrindo variações reais de `messages[].type` (text, button, interactive list/button, statuses).
   - Benefício: reduzir regressões causadas por payloads parciais ou mudanças do provedor.

4. **Fail-fast de configuração em ambientes sensíveis**
   - Tornar recomendação de produção mais explícita no startup (ex.: bloquear envio Meta sem token/phone id quando `ENV=prod`).
   - Benefício: evitar incidentes silenciosos de configuração.

5. **Resiliência de banco para cargas maiores**
   - Revisar sizing do pool (`db_min_conn`, `db_max_conn`) e métricas do pool em runtime.
   - Benefício: prevenir gargalos e timeout sob pico de webhooks.

## Critério de sucesso para o próximo ciclo

- `app/main.py` com menor responsabilidade (parse/orquestração separadas).
- Novas métricas disponíveis em `/metrics` para origem de resposta e erros por categoria.
- Testes cobrindo variações de payload Meta com foco em estabilidade.
