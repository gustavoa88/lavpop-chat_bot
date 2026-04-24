# Chatbot WhatsApp (Meta) + PostgreSQL + IA

Projeto Python do zero para atendimento via **WhatsApp Cloud API (Meta)** com:
- **FastAPI** para webhooks
- **PostgreSQL** para regras, intenções, contexto e logs
- **OpenAI** para fallback de IA quando não houver regra no banco

## 1) Pré-requisitos

- Python 3.11+
- PostgreSQL 14+
- Conta Meta for Developers com WhatsApp Cloud API configurada
- Token e Phone Number ID da Meta
- Chave de API da OpenAI

## 2) Estrutura

```bash
.
├── app/
│   ├── __init__.py
│   ├── config.py
│   ├── db.py
│   ├── main.py
│   └── services.py
├── db/
│   └── schema.sql
├── .env.example
├── requirements.txt
└── README.md
```

## 3) Configuração

```bash
cp .env.example .env
```

Preencha:
- `OPENAI_API_KEY`
- `META_VERIFY_TOKEN`
- `META_WHATSAPP_TOKEN`
- `META_PHONE_NUMBER_ID`
- `META_APP_SECRET` (App Secret da Meta para validar assinatura HMAC do webhook)
- `META_VALIDATE_SIGNATURE` (`true`/`false`, padrão: `true`)
- `META_REQUIRE_APP_SECRET` (`true`/`false`, padrão: `false`)
- dados do PostgreSQL (`DB_*`) **ou** `DATABASE_URL` (quando definido, tem precedência)
- `INACTIVITY_TIMEOUT_MINUTES` (padrão: `15`)
- `INACTIVITY_CHECK_INTERVAL_SECONDS` (padrão: `60`)
- `OBSERVABILITY_INTERNAL_ONLY` (`true`/`false`, padrão: `true`) para restringir `/metrics` e `/health/*` a rede interna
- `APP_ENV` (`dev`/`prod`/`production`; em produção ativa regras estritas de segurança)
- `APP_DEBUG_LOG_MODE` (`true`/`false`, padrão: `false`) para habilitar logs detalhados de diagnóstico (payload recebido, decisão do roteador e resposta da Meta)

> Se `META_VALIDATE_SIGNATURE=true` e `META_APP_SECRET` estiver vazio, a API entra em
> modo de compatibilidade e **não bloqueia** o webhook (apenas loga aviso de segurança).
>
> Para produção, use `APP_ENV=prod` (ou `production`) e `META_REQUIRE_APP_SECRET=true`:
> nesse modo, a aplicação falha na inicialização se a configuração de assinatura não estiver
> estrita (fail-fast de segurança).

## 4) Criar tabelas no PostgreSQL

```bash
psql -h 127.0.0.1 -U postgres -d lavpop_chatbot -f db/schema.sql
```

> A aplicação tenta criar automaticamente o schema `chatbot` e a tabela
> `chatbot.webhook_event_dedup` na inicialização para preservar idempotência
> básica. Ainda assim, aplique o `db/schema.sql` para garantir todas as tabelas
> de negócio (`faq_regras`, `contexto_cliente`, `log_conversas`, etc.).
>
> Se o usuário do banco não tiver permissão DDL, a API apenas registra **warning**
> e segue em modo de compatibilidade (sem quebrar o startup).

## 5) Rodar API

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Health check:

```bash
curl http://localhost:8000/
curl http://localhost:8000/health/live
curl http://localhost:8000/health/ready
curl http://localhost:8000/health/db
curl http://localhost:8000/metrics
```

> Por padrão (`OBSERVABILITY_INTERNAL_ONLY=true`), os endpoints operacionais
> `/metrics` e `/health/*` só aceitam origem interna (IP privado/loopback/link-local).
> Requisições externas recebem HTTP 403.

- `GET /health/live`: confirma que o processo da API está ativo.
- `GET /health/ready`: valida prontidão real consultando o banco (`SELECT 1`).
- `GET /health/db`: retorna status detalhado do banco com latência do check.
- `GET /metrics`: expõe métricas de webhook/processamento e status de banco no formato Prometheus text exposition.

Regras de alertas operacionais (Prometheus) para disponibilidade e erro de processamento:

- `monitoring/prometheus/alerts.yml`
- `docs/ALERTING_SETUP_2026-04-20.md`

## 6) Webhook da Meta

- URL de verificação webhook: `GET /webhook/meta`
- URL para eventos: `POST /webhook/meta`
- A API valida a assinatura `X-Hub-Signature-256` usando HMAC SHA-256 quando
  `META_VALIDATE_SIGNATURE=true` (recomendado para produção).

No painel da Meta, configure:
- Callback URL (ex.: `https://SEU_DOMINIO/webhook/meta`)
- Verify token = valor de `META_VERIFY_TOKEN`
- Use também o `App Secret` do mesmo app para preencher `META_APP_SECRET`.

## 7) Lógica do bot

1. Recebe mensagem via webhook Meta.
2. Normaliza texto e telefone.
3. Se a pessoa enviar uma saudação simples (ex.: `oi`, `olá`, `bom dia`), responde com menu proativo de opções.
   - Quando possível, envia **menu interativo do WhatsApp** (lista com botão `Ver opções`).
   - Se a API da Meta rejeitar menu interativo, faz fallback automático para mensagem de texto.
4. Se a pessoa responder com `1`, `2`, `3`, `4`, `5` **ou selecionar o item da lista pelo título**, busca primeiro resposta cadastrada no banco para o tema; se não houver, retorna fallback do menu.
5. Tenta responder por regra da tabela `chatbot.faq_regras`.
6. Se não achar regra, usa OpenAI (`OPENAI_MODEL`).
7. Salva `chatbot.log_conversas` e atualiza `chatbot.contexto_cliente`.
8. Envia resposta para o usuário via Graph API da Meta.
9. Aplica idempotência por mensagem do webhook (deduplicação por `messages[].id` com fallback por hash), evitando resposta duplicada em reentregas da Meta.
10. Monitora clientes com status `ativo` e, após `INACTIVITY_TIMEOUT_MINUTES` minutos sem interação (padrão `15`, configurável via `.env`), envia uma mensagem gentil de encerramento convidando para voltar à lavanderia.

## 8) Próximos passos recomendados

- Evoluir suíte de testes automatizados (pytest) com cenários de integração reais em PostgreSQL.
- Criar painel administrativo para manter FAQ e intenções.

## 9) Troubleshooting rápido (erro 401 da Meta)

Para diagnóstico aprofundado de webhook/envio, ative temporariamente:

```bash
APP_DEBUG_LOG_MODE=true
```

Com esse modo ativo, o backend adiciona logs com prefixo `[debug_log_mode]` contendo:
- preview do payload bruto recebido no webhook
- evento parseado (tipo/chaves)
- decisão do roteador (modo anterior/novo, ação e motivo)
- resposta da Meta no envio de mensagens/menu (status + body resumido)

Se o log mostrar `Authentication Error` com `code=190` ao enviar mensagem, o webhook está chegando,
mas o token de envio para Graph API falhou na autenticação.

Checklist:
- Confirmar se `META_WHATSAPP_TOKEN` é token de acesso válido do app/WhatsApp Cloud API (não é o `META_VERIFY_TOKEN`).
- Gerar novo token se o atual for temporário/expirado.
- Garantir permissões necessárias (ex.: `whatsapp_business_messaging`).
- Validar se `META_PHONE_NUMBER_ID` corresponde ao número configurado no app da Meta.
- Reiniciar a API após atualizar `.env`.

## 10) Testes automatizados

Suite completa de testes unitários:

```bash
pytest -q
```

Para validar especificamente a assinatura HMAC do webhook e evitar regressões:

```bash
pytest tests/test_hmac_signature_validation.py
```

Cenários cobertos:
- assinatura válida (aceita)
- assinatura inválida (403)
- modo compatibilidade com `META_APP_SECRET` ausente (não bloqueia)

### 10.1) Testes de integração com PostgreSQL real

Há uma suíte de integração (`tests/test_db_integration_postgres.py`) que valida:
- healthcheck/readiness contra PostgreSQL real
- operações `execute`, `fetchone` e `fetchall`
- idempotência real de `try_register_webhook_event` com `ON CONFLICT`

Defina uma conexão de teste e rode somente os cenários de integração:

```bash
export TEST_POSTGRES_DSN='dbname=lavpop_chatbot user=postgres password=postgres host=127.0.0.1 port=5432'
pytest -m integration -q
```

> Os testes de integração são automaticamente ignorados localmente quando `TEST_POSTGRES_DSN` não está definido.
> No CI de release (branch `main`/tags `v*`), a suíte de integração com PostgreSQL é obrigatória como gate.
>
> O job `Deploy release (blocked by integration gate)` só executa depois dos jobs `tests` + `Integration tests (release gate)` com sucesso e ainda valida baseline estrito de segurança via secrets (`APP_ENV`, `META_VALIDATE_SIGNATURE`, `META_REQUIRE_APP_SECRET`, `META_APP_SECRET`).

## 11) Ajuste rápido da regra `o_que_lavar` (PostgreSQL)

Se o menu "4) Serviços disponíveis" estiver retornando itens que a unidade não oferece,
atualize a regra `o_que_lavar` no banco:

```bash
psql -h 127.0.0.1 -U postgres -d lavpop_chatbot -f db/update_o_que_lavar.sql
```

Depois, valide:

```sql
SELECT nome_regra, palavras_chave, resposta
  FROM chatbot.faq_regras
 WHERE nome_regra = 'o_que_lavar';
```

## 12) Roteador de conversas (bot + humano)

O webhook agora funciona como roteador:

```text
Webhook
  -> salva mensagem em chatbot.mensagens
  -> consulta modo da conversa em chatbot.contexto_cliente
  -> bot responde OU atendimento humano assume OU só registra
```

Para bancos já existentes, aplique a migração incremental:

```bash
psql -h 127.0.0.1 -U postgres -d lavpop_chatbot -f db/add_conversation_router.sql
```

Modos principais em `chatbot.contexto_cliente.modo_conversa`:

- `bot`: fluxo automático normal.
- `aguardando_humano`: cliente pediu atendimento humano; novas mensagens são registradas sem resposta automática.
- `humano`: atendimento manual assumido; novas mensagens são registradas sem resposta automática.
- `encerrado`: conversa encerrada; próxima interação volta ao fluxo do bot.

Regras atuais:

- Mensagem `5` ou termos como `atendente`, `falar com humano`, `/humano` e `/pausar` colocam a conversa em `aguardando_humano`.
- Enquanto a conversa estiver em `aguardando_humano` ou `humano`, o bot não responde automaticamente.
- `/retomar`, `retomar bot`, `voltar bot` ou `ativar bot` devolvem a conversa ao modo `bot`.
