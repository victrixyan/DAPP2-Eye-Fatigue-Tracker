#!/usr/bin/env bash
# One-time Raspberry Pi setup. Run once after deploying src/ to the Pi.
#
#   chmod +x linux/setup.sh
#   ./linux/setup.sh
#
# Python libraries are installed by uv from PEP 723 metadata below and in
# server/app.py. Re-run only after adding new system or Python dependencies.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required but was not found on PATH."
  exit 1
fi

echo "Installing OS packages needed for headless camera capture and ML..."

sudo apt-get update
sudo apt-get install -y \
  v4l-utils \
  libglib2.0-0 \
  libgomp1

mkdir -p core/data core/model core/history

export PYTHONPATH="${ROOT}${PYTHONPATH:+:${PYTHONPATH}}"

echo "Prefetching server dependencies via uv..."
uv run python - <<'PY'
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "fastapi>=0.115",
#     "uvicorn[standard]>=0.32",
# ]
# ///
import fastapi
import uvicorn

print("fastapi", fastapi.__version__)
PY

echo "Prefetching camera and ML dependencies via uv (headless)..."
uv run python - <<'PY'
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "numpy>=1.26",
#     "opencv-python-headless>=4.8",
#     "scikit-learn>=1.4",
#     "joblib>=1.3",
# ]
# ///
import cv2
import joblib
import numpy
import sklearn

print("opencv", cv2.__version__)
print("numpy", numpy.__version__)
print("sklearn", sklearn.__version__)
PY

echo ""
echo "Setup complete. Start the server with: ./linux/serve.sh"
