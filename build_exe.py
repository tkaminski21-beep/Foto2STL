"""
Buduje samodzielną wersję (folder z Foto2STL.exe) przez PyInstaller.

  python build_exe.py          # pełna wersja z lokalnym AI (duża: kilka GB)
  python build_exe.py --lite   # bez lokalnego AI: płaskie tryby + chmura (~400 MB)

Wynik: dist/Foto2STL/Foto2STL.exe (dwuklik = GUI). W pełnej wersji folder TripoSR (jeśli jest obok
build_exe.py, np. po install.bat) zostaje skopiowany obok exe automatycznie.
Uruchamiaj z venv projektu, np.:  .venv\\Scripts\\python build_exe.py
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

lite = "--lite" in sys.argv
here = Path(__file__).resolve().parent
args = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--name", "Foto2STL", "--onedir",
        "--collect-all", "gradio", "--collect-all", "gradio_client", "--collect-all", "safehttpx",
        "--collect-all", "groovy", "--collect-all", "manifold3d", "--collect-data", "trimesh",
        "--collect-data", "matplotlib", "--collect-submodules", "foto2stl",
        "--hidden-import", "uvicorn.logging", "--hidden-import", "uvicorn.loops.auto",
        "--hidden-import", "uvicorn.protocols.http.auto", "--hidden-import", "uvicorn.lifespan.on"]
if lite:
    for m in ("torch", "transformers", "rembg", "onnxruntime", "torchvision"):
        args += ["--exclude-module", m]
else:
    # Kod TripoSR jest ładowany w czasie działania z folderu TripoSR, więc PyInstaller nie widzi jego
    # importów; transformers wczytuje modele leniwie (po nazwie), a numba w pymatting (rembg) potrzebuje
    # plików .py, żeby zapisać skompilowane funkcje. Dlatego te moduły dodajemy jawnie.
    hooks = Path(tempfile.mkdtemp(prefix="f2s_hooks_"))
    (hooks / "hook-pymatting.py").write_text('module_collection_mode = "pyz+py"\n', encoding="utf-8")
    args += ["--additional-hooks-dir", str(hooks),
             "--collect-all", "rembg", "--collect-all", "pymatting", "--collect-data", "transformers",
             "--copy-metadata", "transformers", "--copy-metadata", "tokenizers", "--copy-metadata", "huggingface-hub",
             "--copy-metadata", "safetensors", "--copy-metadata", "torch", "--copy-metadata", "numpy",
             "--copy-metadata", "tqdm", "--copy-metadata", "regex", "--copy-metadata", "pyyaml",
             "--copy-metadata", "filelock", "--copy-metadata", "packaging", "--copy-metadata", "requests",
             "--collect-submodules", "omegaconf", "--collect-submodules", "einops",
             "--collect-submodules", "huggingface_hub", "--collect-all", "imageio",
             "--collect-submodules", "transformers.models.auto", "--collect-submodules", "transformers.pipelines",
             "--collect-submodules", "transformers.models.vit", "--collect-submodules", "transformers.models.dinov2",
             "--collect-submodules", "transformers.models.dpt",
             "--collect-submodules", "transformers.models.depth_anything"]
args.append(str(here / "foto2stl.py"))
try:
    import PyInstaller  # noqa: F401
except ImportError:
    subprocess.run([sys.executable, "-m", "pip", "install", "pyinstaller"], check=True)
print(" ".join(args))
code = subprocess.call(args, cwd=here)
if code == 0 and not lite and (here / "TripoSR" / "tsr").is_dir():
    dst = here / "dist" / "Foto2STL" / "TripoSR"
    shutil.copytree(here / "TripoSR", dst, dirs_exist_ok=True, ignore=shutil.ignore_patterns(".git", "examples", "figures"))
    print(f"Skopiowano TripoSR → {dst}")
sys.exit(code)
