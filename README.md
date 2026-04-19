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
- dados do PostgreSQL (`DB_*`)

> Se `META_VALIDATE_SIGNATURE=true` e `META_APP_SECRET` estiver vazio, a API entra em
> modo de compatibilidade e **não bloqueia** o webhook (apenas loga aviso de segurança).
>
> Para produção, recomenda-se `META_REQUIRE_APP_SECRET=true`: nesse modo, a aplicação
> falha na inicialização se `META_APP_SECRET` estiver vazio (fail-fast de segurança).

## 4) Criar tabelas no PostgreSQL

```bash
psql -h 127.0.0.1 -U postgres -d lavpop_chatbot -f db/schema.sql
```

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
```

- `GET /health/live`: confirma que o processo da API está ativo.
- `GET /health/ready`: valida prontidão real consultando o banco (`SELECT 1`).

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
3. Tenta responder por regra da tabela `chatbot.faq_regras`.
4. Se não achar regra, usa OpenAI (`OPENAI_MODEL`).
5. Salva `chatbot.log_conversas` e atualiza `chatbot.contexto_cliente`.
6. Envia resposta para o usuário via Graph API da Meta.

## 8) Próximos passos recomendados

- Adicionar testes automatizados (pytest).
- Criar endpoint de observabilidade (métricas/health DB).
- Criar painel administrativo para manter FAQ e intenções.

## 9) Troubleshooting rápido (erro 401 da Meta)

Se o log mostrar `Authentication Error` com `code=190` ao enviar mensagem, o webhook está chegando,
mas o token de envio para Graph API falhou na autenticação.

Checklist:
- Confirmar se `META_WHATSAPP_TOKEN` é token de acesso válido do app/WhatsApp Cloud API (não é o `META_VERIFY_TOKEN`).
- Gerar novo token se o atual for temporário/expirado.
- Garantir permissões necessárias (ex.: `whatsapp_business_messaging`).
- Validar se `META_PHONE_NUMBER_ID` corresponde ao número configurado no app da Meta.
- Reiniciar a API após atualizar `.env`.
