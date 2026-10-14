#!/bin/bash
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  echo "First run: setting up SceneScout (one time only, needs internet)..."
  python3 -m venv .venv || { echo "Python 3 is not installed. Get it from https://www.python.org/downloads/"; read -r; exit 1; }
fi
./.venv/bin/pip install -q --disable-pip-version-check -r requirements.txt
./.venv/bin/python run.py
