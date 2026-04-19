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
- dados do PostgreSQL (`DB_*`)

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
```

## 6) Webhook da Meta

- URL de verificação webhook: `GET /webhook/meta`
- URL para eventos: `POST /webhook/meta`

No painel da Meta, configure:
- Callback URL (ex.: `https://SEU_DOMINIO/webhook/meta`)
- Verify token = valor de `META_VERIFY_TOKEN`

## 7) Lógica do bot

1. Recebe mensagem via webhook Meta.
2. Normaliza texto e telefone.
3. Tenta responder por regra da tabela `chatbot.faq_regras`.
4. Se não achar regra, usa OpenAI (`OPENAI_MODEL`).
5. Salva `chatbot.log_conversas` e atualiza `chatbot.contexto_cliente`.
6. Envia resposta para o usuário via Graph API da Meta.

## 8) Próximos passos recomendados

- Adicionar testes automatizados (pytest).
- Implementar assinatura HMAC de webhook para segurança avançada.
- Criar endpoint de observabilidade (métricas/health DB).
- Criar painel administrativo para manter FAQ e intenções.
