# Production Operation Checklist

Checklist prático para colocar o chatbot em produção com menos ambiguidade operacional.

## Antes do go-live

- Confirmar `APP_ENV=prod` ou `production` no ambiente de produção.
- Confirmar `META_VALIDATE_SIGNATURE=true`, `META_REQUIRE_APP_SECRET=true` e `APP_DEBUG_LOG_MODE=false`.
- Configurar `META_APP_SECRET` no `environment: production` do GitHub.
- Configurar `PRODUCTION_BASE_URL` para permitir o smoke test pós-deploy.
- Aplicar as migrações versionadas do PostgreSQL antes do restart.
- Garantir que `/metrics` e `/health/*` estejam acessíveis apenas pela rede interna ou por autenticação de borda.
- Ativar branch protection/ruleset em `main` exigindo o check `Integration tests (release gate)`.

## Durante o deploy

- Executar o deploy apenas após `tests` e `integration-release` passarem.
- Rodar o smoke test com `scripts/production_smoke_test.py --base-url <url>` logo após a publicação.
- Validar que `/`, `/health/live`, `/health/ready` e `/health/db` respondem como esperado.
- Interromper o release se o smoke test falhar.

## Depois do go-live

- Registrar os tempos de detecção, mitigação e recuperação em qualquer incidente.
- Monitorar latência de webhook, 5xx, 401/403 de assinatura e disponibilidade de banco.
- Revisar a rotação de `META_APP_SECRET` e demais credenciais em uma cadência definida.
- Manter backup e restore testados para o PostgreSQL.

## Rollback

- Reverter a versão da aplicação.
- Reaplicar a última migration compatível, se necessário.
- Reexecutar o smoke test após o rollback.
- Registrar a causa raiz e a ação corretiva antes de liberar novo deploy.
