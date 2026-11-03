@echo off
cd /d %~dp0
echo === Foto2STL: instalacja ===
py -3.11 -m venv .venv 2>nul || python -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
where nvidia-smi >nul 2>nul && (
  pip install torch --index-url https://download.pytorch.org/whl/cu124
) || (
  pip install torch --index-url https://download.pytorch.org/whl/cpu
)
pip install -r requirements.txt
if not exist TripoSR (
  where git >nul 2>nul && git clone --depth 1 https://github.com/VAST-AI-Research/TripoSR || echo Brak gita - pobierz TripoSR recznie z GitHuba do folderu TripoSR
)
echo.
echo Gotowe. Uruchamiaj przez start.bat
pause
