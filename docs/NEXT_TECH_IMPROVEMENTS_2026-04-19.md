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

O backlog agora é organizado por PR temático em `docs/PR_THEME_ROADMAP.md`.
Os três temas principais são:

1. **Segurança e LGPD**
   - Redaction de logs e previews.
   - Retenção e exposição de dados sensíveis.

2. **Governança de deploy**
   - Preflight, runbook, smoke e checklist de produção.

3. **Arquitetura do webhook**
   - Parsing, orquestração, idempotência, métricas e testes de contrato.

## Critério de sucesso para o próximo ciclo

- Cada novo PR deve nascer de `main` e carregar apenas um tema.
- Cada PR deve ter testes que provem o comportamento alterado.
- Revisões e rollback devem ser possíveis sem depender de um bundle grande de mudanças.
