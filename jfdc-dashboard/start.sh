#!/usr/bin/env bash
# Mac / Linux: double-click or run ./start.sh
cd "$(dirname "$0")"
if [ ! -d .venv ]; then python3 -m venv .venv; fi
source .venv/bin/activate
pip install -q -r requirements.txt
( sleep 2; (open http://localhost:8000 2>/dev/null || xdg-open http://localhost:8000 2>/dev/null) ) &
python app.py
