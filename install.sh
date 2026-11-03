#!/usr/bin/env bash
# Linux / macOS / Raspberry Pi.  Na Pi:  ./install.sh --pi   (bez TripoSR — za ciężki dla Pi 4)
set -e
cd "$(dirname "$0")"
PY=${PYTHON:-python3}
$PY -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
ARCH=$(uname -m)
if command -v nvidia-smi >/dev/null; then pip install torch
elif [ "$ARCH" = "aarch64" ] || [ "$(uname)" = "Darwin" ]; then pip install torch
else pip install torch --index-url https://download.pytorch.org/whl/cpu; fi
pip install -r requirements.txt
if [ "$1" != "--pi" ] && [ ! -d TripoSR ]; then git clone --depth 1 https://github.com/VAST-AI-Research/TripoSR; fi
echo "Gotowe. Start: ./start.sh   (serwer w sieci: ./start.sh --server)"
