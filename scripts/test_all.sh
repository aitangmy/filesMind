#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "============================================================"
echo "          FilesMind Complete CI/CD Check Script             "
echo "============================================================"

echo ""
echo "[1/4] Code Formatting & Linting (Backend) ..."
echo "Running ruff check..."
uv run ruff check .
echo "Running ruff format check..."
uv run ruff format --check .

echo ""
echo "[2/4] Backend Unit Tests & Coverage (pytest) ..."
uv run pytest --cov=backend --cov-report=term-missing -q

echo ""
echo "[3/4] Frontend Verification & Build (vite) ..."
# Ensure npm deps are installed just in case
npm --prefix frontend install --cache /tmp/npm-cache >/dev/null 2>&1 || true

# Check if vitest is configured (run unit tests if exists)
if npm --prefix frontend run | grep -q 'test:unit'; then
    echo "Running frontend unit tests..."
    npm --prefix frontend run test:unit
else
    echo "No frontend unit tests configured (test:unit missing). Skipping."
fi

echo "Building frontend (Vite)..."
npm --prefix frontend run build

echo ""
if [[ "${SKIP_E2E:-0}" == "1" ]]; then
  echo "[4/4] Skipping frontend E2E smoke tests (SKIP_E2E=1)."
else
  echo "[4/4] Running frontend E2E smoke tests (Playwright) ..."
  npm --prefix frontend exec playwright install chromium >/dev/null
  npm --prefix frontend run test:e2e
fi

echo ""
echo "============================================================"
echo "                 All checks passed! 🎉                      "
echo "============================================================"
