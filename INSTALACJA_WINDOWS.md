# Foto2STL na Windows — instalacja krok po kroku

Dwie drogi:
- **A. Zwykła instalacja** (zalecana na własnym komputerze): Python + `install.bat`, uruchamianie przez `start.bat`.
- **B. Wersja .exe**: zbudowana raz, potem działa bez Pythona — także na innym komputerze z Windows.

Wymagania: Windows 10/11 (64-bit), ok. 10 GB wolnego miejsca (z kartą NVIDIA), internet przy instalacji i przy pierwszym użyciu każdego modelu.

---

## A. Zwykła instalacja

### 1. Python
1. Pobierz **Python 3.12 albo 3.13** z https://www.python.org/downloads/windows/ („Windows installer (64-bit)”).
   Nie bierz 3.14, jeśli masz kartę NVIDIA — dla niego nie ma torcha z CUDA, który pobiera instalator, i model liczyłby się na procesorze.
2. W pierwszym oknie instalatora zaznacz **„Add python.exe to PATH”**, potem **Install Now**.

### 2. Git (zalecany)
Pobierz i zainstaluj **Git for Windows**: https://git-scm.com/download/win (domyślne opcje są dobre).
Bez Gita zadziała wszystko oprócz lokalnego TripoSR (pełne 3D bez chmury).

### 3. Pobranie programu
Z Gitem — w oknie `cmd`:
```bat
git clone https://github.com/tkaminski21-beep/Foto2STL.git C:\Foto2STL
```
Bez Gita: na https://github.com/tkaminski21-beep/Foto2STL kliknij **Code → Download ZIP** i rozpakuj do `C:\Foto2STL`.

Nie instaluj na Pulpicie ani w Dokumentach, jeśli synchronizuje je OneDrive — instalacja waży kilka GB.

### 4. Instalacja
W `C:\Foto2STL` kliknij dwukrotnie **`install.bat`** i poczekaj na „Gotowe” (10–20 minut z kartą NVIDIA).
Jeśli pojawi się „System Windows ochronił ten komputer”: **Więcej informacji → Uruchom mimo to**.

### 5. Uruchamianie
- **Interfejs w przeglądarce:** dwuklik na **`start.bat`** → otworzy się http://127.0.0.1:7860.
  Zakładki: *Ze zdjęcia*, *Z opisu*, *Z kilku zdjęć*, *Historia*. Okno konsoli zostaw otwarte — zamknięcie kończy program.
- **Wiersz poleceń:** w `C:\Foto2STL` wpisz `cmd` w pasku adresu Eksploratora, Enter, potem np.:
  ```bat
  .venv\Scripts\python foto2stl.py "%USERPROFILE%\Pictures\zdjecie.jpg" -m relief
  .venv\Scripts\python foto2stl.py "%USERPROFILE%\Pictures\zdjecie.jpg" -m full3d --engine local --height-mm 90
  .venv\Scripts\python foto2stl.py -m multiview --front przod.png --back tyl.png --left lewo.png --right prawo.png -o figurka
  .venv\Scripts\python foto2stl.py --help
  ```
  (`start.bat` zawsze otwiera interfejs — do poleceń z plikami używaj `.venv\Scripts\python foto2stl.py`.)
- **Serwer w sieci** (np. dla telefonu): `.venv\Scripts\python foto2stl.py --server`, potem na telefonie `http://<adres-laptopa>:7860`. Przy pierwszym uruchomieniu Windows zapyta o zgodę w zaporze — zezwól w sieci prywatnej.

### 6. Czy działa karta graficzna
```bat
.venv\Scripts\python -c "import torch; print(torch.__version__, torch.cuda.is_available())"
```
`True` — lokalny TripoSR liczy na karcie (kilkanaście sekund na model). `False` przy karcie NVIDIA — zainstalował się torch dla procesora (najczęściej przez Pythona 3.14): zainstaluj Pythona 3.13, usuń folder `.venv` i uruchom `install.bat` ponownie.

---

## B. Wersja .exe

Po kroku A.4, w oknie `cmd` w `C:\Foto2STL`:
```bat
.venv\Scripts\python build_exe.py
```
(lekka wersja bez lokalnego AI, ok. 400 MB: `.venv\Scripts\python build_exe.py --lite`)

Po 10–20 minutach program jest w **`C:\Foto2STL\dist\Foto2STL\Foto2STL.exe`** — dwuklik otwiera interfejs. Folder `TripoSR` jest kopiowany obok automatycznie. Cały folder `dist\Foto2STL` (5–6 GB w pełnej wersji) możesz przenieść na inny komputer z Windows — Python nie jest tam potrzebny. Z wiersza poleceń exe działa jak `foto2stl.py`, np. `Foto2STL.exe zdjecie.jpg -m relief`.

Jeśli Windows Defender zablokuje exe (programy z PyInstallera bywają fałszywie oznaczane), dodaj folder `dist\Foto2STL` do wyjątków.

---

## Aktualizacja
```bat
cd /d C:\Foto2STL
git pull
```
potem jeszcze raz `install.bat` (i ewentualnie `build_exe.py`). Bez Gita: pobierz nowy ZIP i rozpakuj w to samo miejsce.

## Dobrze wiedzieć
- **Pierwsze użycie każdego modelu** pobiera wagi: model głębi ok. 100 MB, usuwanie tła 176 MB, TripoSR ok. 1,7 GB. Trafiają do `%USERPROFILE%\.cache\huggingface` i `%USERPROFILE%\.rembg`, kolejne uruchomienia działają offline.
- **Chmura (Hunyuan3D-2)** ma darmowy dzienny limit GPU. Większy daje darmowy token z huggingface.co: `setx HF_TOKEN hf_twój_token` (nowe okno `cmd`) albo `--hf-token`.
- **Historia** modeli: `%USERPROFILE%\.foto2stl\history`.

## Rozwiązywanie problemów
| Objaw | Rozwiązanie |
|---|---|
| `python` otwiera Microsoft Store albo „nie rozpoznano polecenia” | Zainstaluj Pythona z python.org z zaznaczonym „Add python.exe to PATH”. W Ustawieniach → Aplikacje → Zaawansowane → *Aliasy wykonywania aplikacji* wyłącz `python.exe` i `python3.exe`. |
| `install.bat`: „Nie udalo sie utworzyc .venv” | Jak wyżej — brak Pythona w PATH. |
| `start.bat` od razu się zamyka | Najpierw `install.bat`. Uruchom `start.bat` z okna `cmd`, żeby zobaczyć komunikat. |
| „Brak gita - pobierz TripoSR recznie” | Zainstaluj Git i uruchom `install.bat` ponownie, albo pobierz ZIP z https://github.com/VAST-AI-Research/TripoSR i rozpakuj jako `C:\Foto2STL\TripoSR`. |
| Przeglądarka się nie otworzyła | Wejdź ręcznie na http://127.0.0.1:7860. |
| Błąd chmury o limicie GPU (quota) | Poczekaj albo ustaw `HF_TOKEN` (wyżej). |
