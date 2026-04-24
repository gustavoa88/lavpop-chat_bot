CREATE SCHEMA IF NOT EXISTS chatbot;

CREATE TABLE IF NOT EXISTS chatbot.intencoes (
  id SERIAL PRIMARY KEY,
  nome_intencao VARCHAR(80) UNIQUE NOT NULL,
  descricao TEXT,
  ativa BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMP NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS chatbot.faq_regras (
  id SERIAL PRIMARY KEY,
  ativo BOOLEAN NOT NULL DEFAULT TRUE,
  prioridade INTEGER NOT NULL DEFAULT 1,
  nome_regra VARCHAR(120) NOT NULL,
  palavras_chave JSONB NOT NULL DEFAULT '[]'::jsonb,
  resposta TEXT NOT NULL,
  humanizada BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMP NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS chatbot.contexto_cliente (
  telefone VARCHAR(50) PRIMARY KEY,
  nome VARCHAR(100),
  ultima_interacao TIMESTAMP NOT NULL DEFAULT NOW(),
  status VARCHAR(50) NOT NULL DEFAULT 'ativo',
  modo_conversa VARCHAR(30) NOT NULL DEFAULT 'bot',
  bot_pausado_ate TIMESTAMP,
  ultimo_handoff_em TIMESTAMP,
  ultimo_handoff_motivo VARCHAR(120),
  ultima_origem_mensagem VARCHAR(40),
  observacoes TEXT,
  ultima_intencao VARCHAR(80),
  ultimo_assunto VARCHAR(120),
  ultima_resposta_tipo VARCHAR(40),
  total_interacoes INT NOT NULL DEFAULT 0,
  updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

ALTER TABLE chatbot.contexto_cliente
  ADD COLUMN IF NOT EXISTS modo_conversa VARCHAR(30) NOT NULL DEFAULT 'bot',
  ADD COLUMN IF NOT EXISTS bot_pausado_ate TIMESTAMP,
  ADD COLUMN IF NOT EXISTS ultimo_handoff_em TIMESTAMP,
  ADD COLUMN IF NOT EXISTS ultimo_handoff_motivo VARCHAR(120),
  ADD COLUMN IF NOT EXISTS ultima_origem_mensagem VARCHAR(40);

CREATE TABLE IF NOT EXISTS chatbot.log_conversas (
  id BIGSERIAL PRIMARY KEY,
  telefone VARCHAR(50) NOT NULL,
  nome_contato VARCHAR(120),
  mensagem_cliente TEXT,
  resposta_bot TEXT,
  origem_resposta VARCHAR(20) NOT NULL,
  regra_nome VARCHAR(120),
  created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS chatbot.webhook_event_dedup (
  event_key VARCHAR(255) PRIMARY KEY,
  payload_hash CHAR(64) NOT NULL,
  source VARCHAR(60) NOT NULL DEFAULT 'meta_webhook',
  processed_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS chatbot.mensagens (
  id BIGSERIAL PRIMARY KEY,
  event_key VARCHAR(255),
  telefone VARCHAR(50) NOT NULL,
  nome_contato VARCHAR(120),
  direcao VARCHAR(20) NOT NULL,
  origem VARCHAR(40) NOT NULL,
  tipo VARCHAR(40) NOT NULL DEFAULT 'text',
  conteudo_texto TEXT,
  payload_json JSONB,
  status VARCHAR(40) NOT NULL DEFAULT 'received',
  resposta_origem VARCHAR(40),
  regra_nome VARCHAR(120),
  intencao VARCHAR(120),
  created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_mensagens_event_key_unique
  ON chatbot.mensagens (event_key)
  WHERE event_key IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_mensagens_telefone_created
  ON chatbot.mensagens (telefone, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_faq_regras_ativo_prioridade
  ON chatbot.faq_regras (ativo, prioridade);

CREATE INDEX IF NOT EXISTS idx_log_conversas_telefone_created
  ON chatbot.log_conversas (telefone, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_webhook_event_dedup_processed_at
  ON chatbot.webhook_event_dedup (processed_at DESC);

CREATE INDEX IF NOT EXISTS idx_contexto_cliente_modo
  ON chatbot.contexto_cliente (modo_conversa, ultima_interacao DESC);
