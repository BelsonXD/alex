#!/usr/bin/env bash
# Secondary launcher for macOS and Linux. Windows users should double-click start.bat.
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
  echo "Install Python 3.11+ from https://www.python.org/downloads/"
  exit 1
fi
if ! command -v node >/dev/null 2>&1; then
  echo "Install Node.js 20+ from https://nodejs.org/en/download"
  exit 1
fi
if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install -r requirements.txt
if [[ ! -d frontend/node_modules ]]; then
  (cd frontend && npm install)
fi
(cd frontend && npm run build)
if [[ ! -f .env ]]; then
  cp .env.example .env
fi
exec python start.py
