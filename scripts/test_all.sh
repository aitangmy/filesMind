#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PKG_DIR="$ROOT_DIR/native/Packages"

if [[ ! -f "$PKG_DIR/Package.swift" ]]; then
  echo "native package not found: $PKG_DIR"
  exit 1
fi

echo "============================================================"
echo "          filesMind Native Build & Test Script              "
echo "============================================================"

echo ""
echo "[1/2] Swift build ..."
(
  cd "$PKG_DIR"
  swift build
)

echo ""
echo "[2/2] Swift tests ..."
(
  cd "$PKG_DIR"
  swift test
)

echo ""
echo "============================================================"
echo "                 Native checks passed                       "
echo "============================================================"
