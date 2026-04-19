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
  observacoes TEXT,
  ultima_intencao VARCHAR(80),
  ultimo_assunto VARCHAR(120),
  ultima_resposta_tipo VARCHAR(40),
  total_interacoes INT NOT NULL DEFAULT 0,
  updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

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

CREATE INDEX IF NOT EXISTS idx_faq_regras_ativo_prioridade
  ON chatbot.faq_regras (ativo, prioridade);

CREATE INDEX IF NOT EXISTS idx_log_conversas_telefone_created
  ON chatbot.log_conversas (telefone, created_at DESC);
