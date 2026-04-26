# Migrações do Banco

Este diretório guarda migrações versionadas para produção. Novas mudanças de
schema devem ser adicionadas aqui antes de alterar o código que depende delas.

Ordem recomendada:

1. Aplicar a migração em staging com usuário dono/admin do schema.
2. Rodar `pytest -q` e testes de integração PostgreSQL.
3. Aplicar em produção.
4. Reiniciar `lavpop-chatbot`.

## Aplicação automatizada

Use o runner versionado para registrar cada migração em
`chatbot.schema_migrations` e bloquear alterações acidentais de arquivos já
aplicados por divergência de checksum.

```bash
python scripts/db_migrate.py
```

O script usa `DATABASE_URL` quando definido; caso contrário, usa `DB_HOST`,
`DB_PORT`, `DB_NAME`, `DB_USER` e `DB_PASSWORD`.

Regra operacional: nunca edite uma migração já aplicada em staging ou produção.
Crie um novo arquivo `.sql` com o próximo prefixo versionado.
