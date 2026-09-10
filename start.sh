#!/usr/bin/env bash
# RouteMind AI - one-click start for macOS and Linux
set -euo pipefail

cd "$(dirname "$0")/backend"

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 was not found. Install Python 3.9 or newer and try again."
  exit 1
fi

echo "Starting RouteMind AI..."
echo "Control room will open at http://127.0.0.1:8000"
echo "Press Ctrl+C to stop the server."
echo
exec python3 run.py "$@"
