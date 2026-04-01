#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

echo "Building OmniClaw npm release artifacts..."

if ! command -v npm >/dev/null 2>&1; then
    echo "Error: npm is required to run build.sh"
    exit 1
fi

echo "Cleaning previous build artifacts..."
rm -rf dist *.tgz

echo "Installing dependencies..."
npm install

echo "Running TypeScript checks..."
npm run typecheck

echo "Building package..."
npm run build

echo "Creating tarball..."
npm pack

echo
echo "Build complete."
echo "Artifacts:"
ls -1 *.tgz dist 2>/dev/null || true
echo
echo "Next:"
echo "  1. Inspect package contents: npm pack --dry-run"
echo "  2. Publish with: npm publish"
