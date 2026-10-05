#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

echo ""
echo "  InventorySync - starting..."
echo ""

if ! command -v python3 &>/dev/null; then
  echo "  ERROR: python3 not found. Install Python 3.11+ first."
  exit 1
fi

if [ ! -d ".venv" ]; then
  echo "  Creating virtual environment..."
  python3 -m venv .venv
  source .venv/bin/activate
  echo "  Installing dependencies..."
  pip install -r requirements.txt
else
  source .venv/bin/activate
fi

echo "  Open http://localhost:5000 in your browser"
echo "  Press Ctrl+C to stop."
echo ""
python app.py
