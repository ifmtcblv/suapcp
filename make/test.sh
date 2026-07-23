#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

"$ROOT_DIR/.venv/bin/pytest" "$ROOT_DIR/tests/" "$@"
