BEGIN;

UPDATE chatbot.mensagens
   SET telefone = regexp_replace(telefone, '[^0-9]', '', 'g')
 WHERE telefone IS NOT NULL
   AND regexp_replace(telefone, '[^0-9]', '', 'g') <> ''
   AND telefone <> regexp_replace(telefone, '[^0-9]', '', 'g');

UPDATE chatbot.log_conversas
   SET telefone = regexp_replace(telefone, '[^0-9]', '', 'g')
 WHERE telefone IS NOT NULL
   AND regexp_replace(telefone, '[^0-9]', '', 'g') <> ''
   AND telefone <> regexp_replace(telefone, '[^0-9]', '', 'g');

CREATE TEMP TABLE tmp_contexto_cliente_phone_normalized ON COMMIT DROP AS
WITH normalized AS (
    SELECT
        telefone AS original_telefone,
        COALESCE(NULLIF(regexp_replace(telefone, '[^0-9]', '', 'g'), ''), telefone) AS normalized_phone,
        total_interacoes,
        ultima_interacao,
        updated_at
      FROM chatbot.contexto_cliente
),
ranked AS (
    SELECT
        original_telefone,
        normalized_phone,
        ROW_NUMBER() OVER (
            PARTITION BY normalized_phone
            ORDER BY ultima_interacao DESC, updated_at DESC, original_telefone ASC
        ) AS rn,
        SUM(total_interacoes) OVER (PARTITION BY normalized_phone) AS merged_total_interacoes,
        MAX(ultima_interacao) OVER (PARTITION BY normalized_phone) AS merged_ultima_interacao,
        MAX(updated_at) OVER (PARTITION BY normalized_phone) AS merged_updated_at
      FROM normalized
)
SELECT *
  FROM ranked;

DELETE FROM chatbot.contexto_cliente c
 USING tmp_contexto_cliente_phone_normalized n
 WHERE c.telefone = n.original_telefone
   AND n.rn > 1;

UPDATE chatbot.contexto_cliente c
   SET telefone = n.normalized_phone,
       total_interacoes = n.merged_total_interacoes,
       ultima_interacao = n.merged_ultima_interacao,
       updated_at = n.merged_updated_at
  FROM tmp_contexto_cliente_phone_normalized n
 WHERE c.telefone = n.original_telefone
   AND n.rn = 1
   AND (
        c.telefone <> n.normalized_phone
        OR c.total_interacoes <> n.merged_total_interacoes
        OR c.ultima_interacao <> n.merged_ultima_interacao
        OR c.updated_at <> n.merged_updated_at
   );

COMMIT;
