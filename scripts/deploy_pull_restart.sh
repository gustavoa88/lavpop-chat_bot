#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/home/gustavo/lavpop-chat_bot"
SERVICE_NAME="lavpop-chatbot"
HEALTH_URL="http://127.0.0.1:8000/health/live"
AUTO_COMMIT_MESSAGE="${AUTO_COMMIT_MESSAGE:-chore: sync local changes before deploy}"

cd "$APP_DIR"

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "Erro: '$APP_DIR' nao e um repositorio git."
  exit 1
fi

current_branch="$(git branch --show-current)"
if [[ "$current_branch" != "main" ]]; then
  echo "Erro: branch atual e '$current_branch', esperado 'main'."
  exit 1
fi

if [[ -n "$(git status --porcelain)" ]]; then
  echo "Alteracoes locais detectadas. Enviando para o Git antes de atualizar:"
  git status --short

  for sensitive_file in .env .env.local .env.production .env.development; do
    if git ls-files --error-unmatch "$sensitive_file" >/dev/null 2>&1; then
      echo "Erro: arquivo sensivel rastreado detectado: $sensitive_file"
      echo "Remova-o do indice antes de publicar."
      exit 1
    fi
  done

  git add -A

  if ! git diff --cached --quiet; then
    git commit -m "$AUTO_COMMIT_MESSAGE"
    git push origin "$current_branch"
  else
    echo "Nenhuma alteracao rastreavel para commitar."
  fi
fi

git pull --ff-only origin main

sudo systemctl restart "$SERVICE_NAME"
sudo systemctl status "$SERVICE_NAME" --no-pager

curl --fail --silent --show-error "$HEALTH_URL"
echo
echo "Deploy concluido."
