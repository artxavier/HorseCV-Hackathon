#!/usr/bin/env bash
# Sobe o servidor de inferencia com a venv do projeto.
# O PYTHONPATH do ROS (se existir no shell) e removido -- ele sombreia o numpy/opencv da venv.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"
exec env -u PYTHONPATH "$HERE/.venv/bin/uvicorn" inference.server:app \
    --host "${HOST:-0.0.0.0}" --port "${PORT:-8001}" "$@"
