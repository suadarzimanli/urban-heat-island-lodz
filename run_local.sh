#!/usr/bin/env bash
# Urban Heat Island — Łódź: run app locally (macOS/Linux)
# Requires Python 3. Opens http://localhost:8000

cd "$(dirname "$0")"
echo "Starting local server in: $(pwd)"
echo "Open http://localhost:8000 in your browser."
echo "Press Ctrl+C to stop."
python3 -m http.server 8000
