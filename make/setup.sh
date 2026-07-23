#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

if [ ! -d "$ROOT_DIR/.venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv "$ROOT_DIR/.venv"
fi

echo "Installing dependencies..."
"$ROOT_DIR/.venv/bin/pip" install --upgrade pip setuptools --quiet
"$ROOT_DIR/.venv/bin/pip" install -r "$ROOT_DIR/requirements.txt" --quiet
"$ROOT_DIR/.venv/bin/pip" install pytest pytest-cov ruff mypy --quiet
echo "Setup complete."
