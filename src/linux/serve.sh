#!/usr/bin/env bash
# Production startup — launch the FastAPI server on the Pi.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export PYTHONPATH="${ROOT}${PYTHONPATH:+:${PYTHONPATH}}"

mkdir -p core/data core/model core/history

exec uv run server/app.py
