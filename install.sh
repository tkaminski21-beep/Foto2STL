#!/usr/bin/env bash
# Linux / macOS / Raspberry Pi / uConsole.
#   ./install.sh        pełna instalacja (z lokalnym TripoSR)
#   ./install.sh --pi   bez TripoSR — Raspberry Pi 4 / uConsole z CM4 są na niego za słabe
set -e
cd "$(dirname "$0")"
PY=${PYTHON:-python3}

if ! $PY -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then
  echo "Potrzebny Python 3.10 lub nowszy (jest: $($PY --version 2>&1)). Inny interpreter: PYTHON=python3.11 ./install.sh"
  exit 1
fi
if ! $PY -m venv .venv || [ ! -f .venv/bin/activate ]; then
  echo "Nie udało się utworzyć środowiska .venv."
  echo "Debian / Raspberry Pi OS / uConsole:  sudo apt install python3-venv python3-dev git"
  rm -rf .venv
  exit 1
fi
. .venv/bin/activate
python -m pip install --upgrade pip

ARCH=$(uname -m)
TORCH_OK=1
if command -v nvidia-smi >/dev/null; then
  pip install torch || TORCH_OK=0
elif [ "$ARCH" = "x86_64" ] && [ "$(uname)" = "Linux" ]; then
  # wersja tylko-CPU jest kilka razy mniejsza; gdy serwer PyTorcha jest niedostępny — zwykły torch z PyPI
  pip install torch --index-url https://download.pytorch.org/whl/cpu \
    || { echo "download.pytorch.org niedostępny — instaluję torch z PyPI (większy, działa też na CPU)"; pip install torch; } \
    || TORCH_OK=0
else
  # aarch64 (Raspberry Pi 64-bit, uConsole), macOS: torch z PyPI jest już w wersji CPU
  pip install torch || TORCH_OK=0
fi
if [ "$TORCH_OK" = 0 ]; then
  echo "UWAGA: nie udało się zainstalować PyTorcha (system 32-bitowy? 'uname -m' = $ARCH)."
  echo "       Działać będą tryby heightmap/lithophane i silniki chmurowe (--engine hunyuan3d);"
  echo "       relief i lokalny TripoSR wymagają 64-bitowego systemu."
fi

pip install -r requirements.txt

if [ "$1" != "--pi" ] && [ "$TORCH_OK" = 1 ] && [ ! -d TripoSR ]; then
  if command -v git >/dev/null; then
    git clone --depth 1 https://github.com/VAST-AI-Research/TripoSR
  else
    echo "Brak gita — TripoSR pobierz ręcznie z https://github.com/VAST-AI-Research/TripoSR do folderu TripoSR"
  fi
fi
chmod +x start.sh install.sh 2>/dev/null || true
echo "Gotowe. Start: bash start.sh   (serwer w sieci: bash start.sh --server)"
