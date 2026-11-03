#!/usr/bin/env python3
"""Foto2STL — uruchom: python foto2stl.py --help   |   python foto2stl.py --gui"""
import os
import sys

if getattr(sys, "frozen", False):
    # wersja .exe: numba (rembg → pymatting) nie może zapisywać skompilowanych funkcji obok kodu
    os.environ.setdefault("NUMBA_CACHE_DIR", os.path.join(os.path.expanduser("~"), ".foto2stl", "numba"))

_here = os.path.dirname(os.path.abspath(__file__))
if not getattr(sys, "frozen", False) and not os.path.isfile(os.path.join(_here, "foto2stl", "__init__.py")):
    sys.exit(f"Foto2STL: obok {os.path.abspath(__file__)} brakuje folderu foto2stl/ z kodem programu.\n"
             "Uruchamiaj z rozpakowanego folderu projektu (tam są install.sh, start.sh i folder foto2stl/).")

from foto2stl.cli import main  # noqa: E402

if __name__ == "__main__":
    main()
