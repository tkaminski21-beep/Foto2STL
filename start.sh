#!/usr/bin/env bash
# Uruchamianie z dowolnego miejsca:  bash ~/foto2stl/start.sh zdjecie.jpg -m relief
# (ścieżki do zdjęć liczą się względem katalogu, w którym jesteś)
D="$(cd "$(dirname "$0")" && pwd)"
if [ ! -f "$D/foto2stl/__init__.py" ]; then
  echo "Foto2STL: w $D brakuje folderu foto2stl/ z kodem programu."
  echo "Uruchamiaj start.sh z rozpakowanego folderu projektu (tam są też install.sh i folder foto2stl/)."
  exit 1
fi
if [ ! -f "$D/.venv/bin/activate" ]; then
  echo "Foto2STL: brak środowiska $D/.venv — najpierw:  bash $D/install.sh --pi   (albo bez --pi, z TripoSR)"
  exit 1
fi
. "$D/.venv/bin/activate"
if [ $# -eq 0 ]; then exec python "$D/foto2stl.py" --gui; else exec python "$D/foto2stl.py" "$@"; fi
