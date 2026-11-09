# Foto2STL 2.0.1 — poprawki po testach trybów AI

## Instalacja
- `install.sh`: gdy `download.pytorch.org` jest niedostępny, torch instaluje się z PyPI (wcześniej instalacja przerywała się na x86_64).
- `install.sh`: czytelny komunikat, gdy brakuje `python3-venv` (częste na czystym Debianie/uConsole), sprawdzenie wersji Pythona (≥ 3.10), ostrzeżenie dla 32-bitowego ARM zamiast przerwania.
- W paczce `install.sh`/`start.sh` nie miały prawa wykonywania → `./install.sh` dawało „Permission denied”. README używa teraz `bash install.sh`, a skrypty mają ustawione `+x`.
- `start.sh`/`foto2stl.py`/`install.sh` uruchomione poza folderem projektu dawały `ModuleNotFoundError: 'foto2stl' is not a package` — teraz mówią wprost, czego brakuje (folderu `foto2stl/` albo `.venv`). `start.sh` nie zmienia już katalogu, więc działa z dowolnego miejsca, a ścieżki zdjęć liczą się względem bieżącego katalogu.
- `install.bat`: to samo zapasowe źródło torcha (nieprzetestowane — brak Windowsa).
- Sprawdzone: wszystkie zależności mają gotowe paczki dla ARM64 (Python 3.11 i 3.13) — na uConsole nic się nie kompiluje.

## Relief (Depth Anything V2) i usuwanie tła
- rembg od 2.0.7x domyślnie pobiera model `bria-rmbg` (1 GB, licencja niekomercyjna). Foto2STL jawnie używa `u2net` (176 MB) — relief z `--remove-bg` 180 s → 20 s. Nowa opcja `--rembg-model` (np. `u2netp`, 5 MB, dla Pi/uConsole).
- Komunikat „Ładuję model usuwania tła” pojawia się przed importem rembg (pierwszy import kompiluje moduły — na ARM kilka minut, wyglądało na zawieszenie).
- Czytelny błąd, gdy modelu głębi nie da się pobrać (zamiast mylącego komunikatu transformers).

## full3d lokalnie (TripoSR)
- **Główny błąd:** transformers 5 zmienił nazwy wag enkodera ViT (`encoder.layer.N.attention.attention.query` → `layers.N.attention.q_proj`…). Oryginalne ładowanie TripoSR kończyło się „Missing key(s) in state_dict”. Foto2STL tłumaczy nazwy przy wczytywaniu (zweryfikowane numerycznie względem transformers 4.35).
- Wagi wczytywane przez `mmap` + `assign=True`: szczyt RAM przy ładowaniu 4,5 → 2,8 GB.
- Bezpieczne `torch.load(weights_only=True)` (domyślne od torch 2.6) z awaryjnym trybem tylko dla oficjalnego pliku.
- Ostrzeżenie przy < 6 GB RAM (TripoSR: ~4 GB przy `--mc-res 128`, ~5 GB przy 256); czytelny błąd przy braku dostępu do huggingface.co.

## Hunyuan3D-2 (chmura)
- API Space'a sprawdzone ze źródłem (`gradio_app.py`): `/shape_generation`, `/generation_all` i nazwy parametrów zgadzają się z profilami — profile bez zmian.
- **Błąd:** publiczny Space ma wyłączone tekstury („Texture Generation (Unavailable)”), a `/generation_all` po wygenerowaniu kształtu kończy się błędem. Dotyczyło `--engine hunyuan3d-color` i `--engine hunyuan3d --color`. Teraz program wykrywa ukryty przycisk i od razu generuje sam kształt (bez marnowania limitu GPU), a przy błędzie tekstur ponawia bez koloru.
- `--cloud-api` pokazuje wartości domyślne parametrów i oznacza endpointy ukryte w interfejsie; brak połączenia i błędy Space'a (np. limit GPU) dają czytelny komunikat zamiast tracebacku.

## GUI / serwer
- Opcje z wiersza poleceń (`--engine`, `--hf-token`, `--mqtt`, `--depth-model`, `--rembg-model`…) obowiązują teraz też w GUI (wcześniej tylko w REST i katalogu obserwowanym); ustawienia z interfejsu mają pierwszeństwo.

## Domyślna skala
- Domyślna wysokość modeli 3D (`--height-mm`, suwak w GUI) to teraz **33 mm** — standardowa skala modelarska (wcześniej 80 mm).
