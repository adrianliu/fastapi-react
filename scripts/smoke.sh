#!/usr/bin/env bash
# Run before every commit. Exits non-zero on the first failure.
#   1. backend lint + format check (ruff), type check (mypy --strict), unit tests (pytest, temp DB)
#   2. frontend lint (eslint), format check (prettier), type check (tsc) + production build
#   3. live API check through the Vite proxy (skipped with a warning if the dev servers are not running)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "==> backend lint, types, tests"
cd "$ROOT/backend"
for tool in pytest ruff mypy; do
  [ -x ".venv/bin/$tool" ] || { uv venv -q 2>/dev/null || true; uv pip install -q -r requirements-dev.txt; break; }
done
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy .
.venv/bin/pytest -q

echo "==> frontend lint, types, build"
cd "$ROOT/frontend"
[ -x node_modules/.bin/eslint ] || npm install --silent
npm run lint --silent
npm run format:check --silent
npm run build --silent >/dev/null  # runs tsc -b first
echo "build ok"
rm -rf dist

echo "==> live API via proxy (http://localhost:5173/api)"
if curl -sf -o /dev/null http://localhost:5173/api/home; then
  curl -sf localhost:5173/api/home | jq -e 'has("sessions")' >/dev/null
  curl -sf 'localhost:5173/api/sessions?limit=1' | jq -e 'has("total") and has("items")' >/dev/null
  echo "live API ok (/api/home, /api/sessions)"
else
  echo "WARN: dev servers not running; live API check skipped (start them per CLAUDE.md)"
fi
echo "==> smoke OK"
