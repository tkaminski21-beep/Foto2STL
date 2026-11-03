"""
Buduje samodzielną wersję (folder z Foto2STL.exe) przez PyInstaller.

  python build_exe.py          # pełna wersja z lokalnym AI (duża: kilka GB)
  python build_exe.py --lite   # bez lokalnego AI: płaskie tryby + chmura (~400 MB)

Wynik: dist/Foto2STL/Foto2STL.exe (dwuklik = GUI). TripoSR skopiuj obok exe do folderu TripoSR.
"""
import subprocess
import sys

lite = "--lite" in sys.argv
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
    args += ["--collect-all", "rembg", "--collect-data", "transformers", "--copy-metadata", "transformers",
             "--copy-metadata", "tokenizers", "--copy-metadata", "huggingface-hub", "--copy-metadata", "safetensors"]
args.append("foto2stl.py")
try:
    import PyInstaller  # noqa: F401
except ImportError:
    subprocess.run([sys.executable, "-m", "pip", "install", "pyinstaller"], check=True)
print(" ".join(args))
sys.exit(subprocess.call(args))
