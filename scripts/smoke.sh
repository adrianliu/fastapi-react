#!/usr/bin/env bash
# Run before every commit. Exits non-zero on the first failure.
#   1. backend unit tests (pytest, temp DB)
#   2. frontend production build
#   3. live API check through the Vite proxy (skipped with a warning if the dev servers are not running)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "==> backend tests"
cd "$ROOT/backend"
[ -x .venv/bin/pytest ] || { uv venv -q 2>/dev/null || true; uv pip install -q -r requirements-dev.txt; }
.venv/bin/pytest -q

echo "==> frontend build"
cd "$ROOT/frontend"
[ -d node_modules ] || npm install --silent
npm run build --silent >/dev/null && echo "build ok"
rm -rf dist

echo "==> live API via proxy (http://localhost:5173/api)"
if curl -sf -o /dev/null http://localhost:5173/api/notes; then
  id=$(curl -sf -XPOST localhost:5173/api/notes -H 'Content-Type: application/json' -d '{"text":"smoke"}' | jq -r .id)
  curl -sf localhost:5173/api/notes | jq -e --argjson id "$id" 'any(.id == $id)' >/dev/null
  code=$(curl -s -o /dev/null -w '%{http_code}' -XDELETE "localhost:5173/api/notes/$id")
  [ "$code" = 204 ] || { echo "DELETE returned $code"; exit 1; }
  echo "live API ok (created/listed/deleted note $id)"
else
  echo "WARN: dev servers not running; live API check skipped (start them per CLAUDE.md)"
fi
echo "==> smoke OK"
