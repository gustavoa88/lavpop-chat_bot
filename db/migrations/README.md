# Migrações do Banco

Este diretório guarda migrações versionadas para produção. Novas mudanças de
schema devem ser adicionadas aqui antes de alterar o código que depende delas.

Ordem recomendada:

1. Aplicar a migração em staging com usuário dono/admin do schema.
2. Rodar `pytest -q` e testes de integração PostgreSQL.
3. Aplicar em produção.
4. Reiniciar `lavpop-chatbot`.

