# Production Edge Hardening

## Nginx

- Copie `deploy/nginx/lavpop-chatbot.http.conf` para um arquivo incluído no contexto `http` do Nginx.
- Copie `deploy/nginx/lavpop-chatbot.server.conf` para `sites-available` e habilite o site.
- Atualize `server_name` para o domínio real.
- Garanta que a aplicação continue ouvindo apenas em `127.0.0.1:8000`.

## Autenticação operacional

- Crie `/etc/nginx/.htpasswd-lavpop-chatbot` para proteger `/metrics` e `/health/*`.
- Mantenha esse arquivo fora do repositório.

## Rate limit

- O template aplica limite por IP no webhook.
- Ajuste a taxa se a Meta ou a borda da sua infraestrutura exigirem valores diferentes.

## Verificação

- Executar `nginx -t` antes de recarregar o serviço.
- Validar que o webhook responde e que `/metrics` e `/health/*` não ficam acessíveis publicamente.
- Rodar `scripts/edge_diagnose.py --domain <dominio> --ssh-target <user@host>` para separar DNS, borda, firewall e serviço.
