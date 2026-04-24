CREATE SCHEMA IF NOT EXISTS chatbot;

ALTER TABLE chatbot.contexto_cliente
  ADD COLUMN IF NOT EXISTS modo_conversa VARCHAR(30) NOT NULL DEFAULT 'bot',
  ADD COLUMN IF NOT EXISTS bot_pausado_ate TIMESTAMP,
  ADD COLUMN IF NOT EXISTS ultimo_handoff_em TIMESTAMP,
  ADD COLUMN IF NOT EXISTS ultimo_handoff_motivo VARCHAR(120),
  ADD COLUMN IF NOT EXISTS ultima_origem_mensagem VARCHAR(40);

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

CREATE INDEX IF NOT EXISTS idx_contexto_cliente_modo
  ON chatbot.contexto_cliente (modo_conversa, ultima_interacao DESC);
