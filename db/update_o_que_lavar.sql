-- Ajusta a regra usada pelo menu "4) Serviços disponíveis"
-- para refletir apenas os serviços realmente oferecidos.

UPDATE chatbot.faq_regras
   SET ativo = TRUE,
       prioridade = 1,
       palavras_chave = '["o que da pra lavar", "o que posso lavar", "o que pode lavar", "quais roupas posso lavar", "servicos disponiveis"]'::jsonb,
       resposta = '✅ *O que lavamos na unidade*\n- Roupas do dia a dia\n- Peças delicadas\n\nSe quiser, me diga a peça específica e eu confirmo para você 🙂',
       humanizada = TRUE,
       updated_at = NOW()
 WHERE nome_regra = 'o_que_lavar';

INSERT INTO chatbot.faq_regras (
  ativo,
  prioridade,
  nome_regra,
  palavras_chave,
  resposta,
  humanizada,
  created_at,
  updated_at
)
SELECT
  TRUE,
  1,
  'o_que_lavar',
  '["o que da pra lavar", "o que posso lavar", "o que pode lavar", "quais roupas posso lavar", "servicos disponiveis"]'::jsonb,
  '✅ *O que lavamos na unidade*\n- Roupas do dia a dia\n- Peças delicadas\n\nSe quiser, me diga a peça específica e eu confirmo para você 🙂',
  TRUE,
  NOW(),
  NOW()
WHERE NOT EXISTS (
  SELECT 1
    FROM chatbot.faq_regras
   WHERE nome_regra = 'o_que_lavar'
);
