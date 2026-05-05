#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/home/gustavo/lavpop-chat_bot"
SERVICE_NAME="lavpop-chatbot"
HEALTH_URL="http://127.0.0.1:8000/health/live"

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
  echo "Erro: existem alteracoes locais. Commit/stash antes de atualizar."
  git status --short
  exit 1
fi

git pull --ff-only origin main

sudo systemctl restart "$SERVICE_NAME"
sudo systemctl status "$SERVICE_NAME" --no-pager

curl --fail --silent --show-error "$HEALTH_URL"
echo
echo "Deploy concluido."
