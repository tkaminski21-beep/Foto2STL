#!/usr/bin/env bash
cd "$(dirname "$0")"
. .venv/bin/activate
if [ $# -eq 0 ]; then exec python foto2stl.py --gui; else exec python foto2stl.py "$@"; fi
