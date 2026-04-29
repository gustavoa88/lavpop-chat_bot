# Blueprint técnico: IA com respostas factuais + personalidade sazonal

Este documento descreve uma implementação incremental para o stack atual do projeto (**FastAPI + PostgreSQL + OpenAI**) para melhorar naturalidade sem alucinação.

## 1) Objetivo

Separar claramente:
- **Fato**: responder somente com base em evidência do banco.
- **Estilo**: ajustar tom/persona por período (ex.: Dia das Mães, Namorados, Natal).

Princípio: **"não inventar"** sempre tem prioridade sobre tom criativo.

---

## 2) Encaixe no stack atual

Pontos do código que já suportam a evolução:
- Entrada e orquestração de webhook em `app/main.py`.
- Lógica de serviço em `app/services.py`.
- Contexto por cliente e roteamento de conversa (`bot`/`humano`) em `app/conversation_router.py`.
- Persistência PostgreSQL via `app/db.py` e migrações em `db/migrations/`.

Estratégia recomendada:
1. Manter fluxo principal atual (menu, regras, fallback IA).
2. Inserir um **pipeline de geração em 2 etapas** dentro de `ChatService`:
   - Etapa A: montar **resposta factual canônica** (com evidências).
   - Etapa B: aplicar **transformação de estilo** pela persona ativa.

---

## 3) Modelo de dados (PostgreSQL)

> Use o schema `chatbot` já existente no projeto.

### 3.1 Tabela de personas

```sql
CREATE TABLE IF NOT EXISTS chatbot.personas (
  id BIGSERIAL PRIMARY KEY,
  code TEXT NOT NULL UNIQUE,                  -- ex.: default, maes_2026, natal_2026
  display_name TEXT NOT NULL,
  locale TEXT NOT NULL DEFAULT 'pt-BR',
  tone TEXT NOT NULL,                         -- ex.: neutro, fraternal, romantico, festivo
  style_rules JSONB NOT NULL DEFAULT '{}'::jsonb,
  safety_rules JSONB NOT NULL DEFAULT '{}'::jsonb,
  enabled BOOLEAN NOT NULL DEFAULT true,
  priority INT NOT NULL DEFAULT 100,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

`style_rules` sugerido:
- `max_length` (curta/media/longa)
- `emoji_level` (0-3)
- `greeting_template`
- `closing_template`
- `forbidden_phrases` (array)

`safety_rules` sugerido:
- `never_fabricate=true`
- `sensitive_mode=minimal_style`
- `fallback_when_unknown` (mensagem padrão)

### 3.2 Agenda de campanhas/persona ativa

```sql
CREATE TABLE IF NOT EXISTS chatbot.persona_campaigns (
  id BIGSERIAL PRIMARY KEY,
  persona_code TEXT NOT NULL REFERENCES chatbot.personas(code),
  campaign_name TEXT NOT NULL,
  start_date DATE NOT NULL,
  end_date DATE NOT NULL,
  channel TEXT NOT NULL DEFAULT 'whatsapp',
  enabled BOOLEAN NOT NULL DEFAULT true,
  priority INT NOT NULL DEFAULT 100,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CHECK (end_date >= start_date)
);

CREATE INDEX IF NOT EXISTS idx_persona_campaigns_window
  ON chatbot.persona_campaigns (start_date, end_date, enabled, priority);
```

Resolução sugerida:
- Busca campanhas ativas para `CURRENT_DATE`.
- Ordena por `priority ASC`.
- Se não houver ativa, usa persona `default`.

### 3.3 Log de evidências e resposta (auditoria)

```sql
CREATE TABLE IF NOT EXISTS chatbot.response_audit (
  id BIGSERIAL PRIMARY KEY,
  phone_hash TEXT NOT NULL,
  user_message TEXT NOT NULL,
  canonical_answer TEXT,
  styled_answer TEXT,
  persona_code TEXT NOT NULL,
  evidence JSONB NOT NULL DEFAULT '[]'::jsonb,
  confidence NUMERIC(5,4),
  policy_result JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

`evidence` deve registrar origem (ex.: regra FAQ, item de menu, contexto, consulta SQL).

---

## 4) Prompt de sistema (produção)

Use um prompt estruturado para fallback IA no OpenAI.

### 4.1 Prompt base (camada factual)

```text
Você é assistente da LavPop.

OBJETIVO:
- Responder somente com base nas EVIDÊNCIAS fornecidas.
- Se evidência insuficiente: diga explicitamente que não encontrou dados e peça detalhe objetivo.

REGRAS DE SEGURANÇA:
- Nunca invente preço, prazo, política, horário ou disponibilidade.
- Não afirme ações que não pode executar.
- Em pedidos sensíveis (dados pessoais, pagamento, segurança), seja direto e minimalista.

FORMATO:
- Resposta curta, clara, em pt-BR.
- Se possível, use bullets.
- Inclua próximo passo acionável.
```

### 4.2 Prompt de estilo (persona)

```text
Aplique o estilo da persona sem alterar fatos.

PERSONA_ATIVA:
- code: {{persona_code}}
- tone: {{tone}}
- style_rules: {{style_rules_json}}

RESTRIÇÕES:
- Não remover avisos de segurança.
- Não adicionar novos fatos.
- Se houver conflito entre estilo e segurança/fatos, manter segurança/fatos.
```

### 4.3 Contrato de saída (recomendado)

Pedir JSON para facilitar validação:

```json
{
  "answer": "texto final para usuário",
  "used_evidence_ids": ["faq:123", "menu:2"],
  "insufficient_evidence": false,
  "safety_flags": []
}
```

---

## 5) Fluxo de decisão (runtime)

1. **Entrada**: mensagem chega via `/webhook/meta`.
2. **Router**: respeitar modo `humano`/`bot` já existente.
3. **Intent + recuperação**:
   - tentar menu/regras existentes;
   - recuperar evidências de FAQ/contexto.
4. **Policy gate factual**:
   - se `evidence_count == 0`: resposta de insuficiência (sem inventar);
   - se tópico sensível: reduzir estilo.
5. **Resolução de persona ativa**:
   - consultar `persona_campaigns` pela data UTC atual;
   - fallback para `default`.
6. **Geração final**:
   - montar resposta canônica factual;
   - aplicar camada de estilo;
   - validar que estilo não alterou fatos.
7. **Persistência**:
   - salvar `log_conversas` atual;
   - salvar `response_audit` com evidências/persona/policy.
8. **Envio Meta API**.

---

## 6) Regras de qualidade (anti-alucinação)

Checklist antes de enviar:
- `answer` menciona apenas campos presentes nas evidências?
- há número/preço/prazo sem origem? bloquear.
- houve transformação de estilo acima do permitido para intenção sensível? reduzir.
- confiança baixa + sem evidência robusta? usar resposta de confirmação.

Métrica recomendada:
- `% respostas com evidence_count > 0`
- `% respostas insuficientes` (bom para descobrir lacunas de conteúdo)
- `% handoff para humano`
- CSAT por persona/campanha

---

## 7) Plano de implementação no repositório

### Fase 1 (baixo risco)
- Criar migração para `personas`, `persona_campaigns`, `response_audit`.
- Incluir métodos de leitura em `app/db.py`.
- Em `app/services.py`, introduzir:
  - `resolve_active_persona(now_utc)`
  - `build_canonical_answer(...)`
  - `apply_persona_style(...)`
  - `validate_no_fact_drift(...)`

### Fase 2 (observabilidade)
- Exportar métricas em `app/observability.py`:
  - `persona_selected_total{persona_code}`
  - `insufficient_evidence_total`
  - `fact_drift_block_total`

### Fase 3 (otimização)
- Cache de persona ativa por janela curta (ex.: 60s).
- Testes A/B de persona por campanha.

---

## 8) Exemplos de personas iniciais

### default
- tom: profissional acolhedor
- emoji_level: 1
- max_length: curta

### maes_2026
- tom: fraternal e acolhedor
- emoji_level: 1
- restrição: sem infantilização

### namorados_2026
- tom: romântico leve
- emoji_level: 1
- restrição: evitar insinuações

### natal_2026
- tom: festivo objetivo
- emoji_level: 2
- restrição: não exagerar em metáforas

---

## 9) Exemplo de decisão de persona por datas (UTC)

- Dia das Mães: `2026-05-01` a `2026-05-31`
- Namorados: `2026-06-01` a `2026-06-15`
- Natal: `2026-12-01` a `2026-12-26`

> Sempre registrar no banco datas absolutas (YYYY-MM-DD) para evitar ambiguidades de "hoje/amanhã" entre fusos.
