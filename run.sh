#!/usr/bin/env bash
set -e

# 1. Create / activate virtualenv
if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate

# 2. Upgrade pip and install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# 3. Install playwright browsers (required for JS rendering)
python -m playwright install --with-deps

# 4. Start server on http://localhost:8000
uvicorn main:app --host 0.0.0.0 --port 8000
