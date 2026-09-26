#!/usr/bin/env bash
# Opens the Business Reports app in your browser (Mac / Linux).
set -e
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  echo "First run: setting up, this takes a few minutes..."
  python3 -m venv .venv
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -r requirements.txt
fi
exec .venv/bin/python -m streamlit run app.py --browser.gatherUsageStats false "$@"
