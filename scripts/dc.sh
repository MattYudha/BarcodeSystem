#!/usr/bin/env bash
# Wrapper docker compose (Linux/CI/WSL). Di Git Bash Windows tanpa docker, otomatis lewat WSL.
#   scripts/dc.sh up -d
#   scripts/dc.sh --profile full up -d --build
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

ARGS=(compose -f infra/docker-compose.yml)
[[ -f .env ]] && ARGS+=(--env-file .env)

if command -v docker >/dev/null 2>&1; then
  exec docker "${ARGS[@]}" "$@"
fi

DISTRO="${BHV_WSL_DISTRO:-Ubuntu-22.04}"
if command -v wsl.exe >/dev/null 2>&1; then
  # Git Bash: matikan konversi path MSYS; wsl --cd menerima path Windows.
  export MSYS_NO_PATHCONV=1
  exec wsl.exe -d "$DISTRO" --cd "$(cygpath -w "$ROOT")" -- docker "${ARGS[@]}" "$@"
fi

echo "docker tidak ditemukan (dan WSL tidak tersedia)" >&2
exit 1
