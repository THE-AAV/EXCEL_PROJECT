#!/bin/sh
# Runs the Business Reports web app on this computer for everyone on the office network (Mac / Linux).
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  echo "First run: setting up, this takes a few minutes..."
  python3 -m venv .venv && .venv/bin/python -m pip install --upgrade pip
fi
.venv/bin/python -m pip install -q -r requirements-server.txt || exit 1
exec .venv/bin/python -m server.office
