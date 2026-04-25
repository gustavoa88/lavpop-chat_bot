#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Uso:
  scripts/git_push.sh "mensagem do commit"

Opções:
  SKIP_TESTS=1  pula a execução de pytest -q antes do commit

Exemplo:
  scripts/git_push.sh "feat: ajuste no bot"
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

commit_message="${1:-}"
if [[ -z "$commit_message" ]]; then
  echo "Erro: informe a mensagem do commit."
  usage
  exit 1
fi

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/.." && pwd)"
cd "$repo_root"

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "Erro: este diretório não é um repositório git."
  exit 1
fi

branch="$(git branch --show-current)"
if [[ -z "$branch" ]]; then
  echo "Erro: branch destacada. Faça checkout de uma branch antes de publicar."
  exit 1
fi

if ! git remote get-url origin >/dev/null 2>&1; then
  echo "Erro: remoto 'origin' não encontrado."
  exit 1
fi

for sensitive_file in .env .env.local .env.production .env.development; do
  if git ls-files --error-unmatch "$sensitive_file" >/dev/null 2>&1; then
    echo "Erro: arquivo sensível rastreado detectado: $sensitive_file"
    echo "Remova-o do índice antes de publicar."
    exit 1
  fi
done

if [[ "${SKIP_TESTS:-0}" != "1" ]]; then
  pytest -q
fi

git add -A

if git diff --cached --quiet; then
  echo "Nada para commitar."
  exit 0
fi

git commit -m "$commit_message"
git push -u origin "$branch"
