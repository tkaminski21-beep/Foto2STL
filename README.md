# Foto2STL 2.0

Zdjęcie, kilka zdjęć albo sam opis → model gotowy do druku 3D. Lokalna i darmowa alternatywa dla Meshy.

## Szybki start

Rozpakuj paczkę i pracuj w jej folderze (tam, gdzie leżą `install.sh`, `start.sh` i podfolder `foto2stl/`). `start.sh` można potem wywołać z dowolnego miejsca, np. `bash ~/foto2stl/start.sh zdjecie.jpg -m relief`.

**Windows:** uruchom `install.bat`, potem `start.bat` (otworzy się przeglądarka).
**Linux / macOS:** `bash install.sh`, potem `bash start.sh`.
**Raspberry Pi / uConsole:** `bash install.sh --pi`, potem `bash start.sh --server` albo `bash start.sh` (szczegóły niżej).

### Wersja .exe na Windows (bez Pythona na docelowym komputerze)

Po `install.bat`, w folderze projektu:

```bat
.venv\Scripts\python build_exe.py          :: pełna: lokalne AI (TripoSR, relief) — kilka GB
.venv\Scripts\python build_exe.py --lite   :: lekka: tryby płaskie + chmura — ok. 400 MB
```

Wynik: folder `dist\Foto2STL` z `Foto2STL.exe` (dwuklik = GUI w przeglądarce, z wiersza poleceń działa jak `foto2stl.py`). W pełnej wersji folder `TripoSR` jest kopiowany obok exe automatycznie. Cały folder `dist\Foto2STL` można przenieść na inny komputer; wagi modeli pobierają się przy pierwszym użyciu do `%USERPROFILE%\.cache\huggingface`.

## Co potrafi

| Wejście | Tryb | Silnik |
|---|---|---|
| zdjęcie | `full3d` — pełny obiekt | lokalnie TripoSR albo chmura Hunyuan3D-2 |
| kilka zdjęć | `multiview` — przód/tył/boki, prawdziwy tył obiektu | chmura Hunyuan3D-2mv |
| opis | `text3d` — opis → obraz (FLUX) → model | chmura + wybrany silnik 3D |
| zdjęcie | `relief` — płaskorzeźba z mapy głębi | lokalnie Depth Anything V2 |
| zdjęcie | `heightmap` — jasność = wysokość (logo, napisy) | bez AI |
| zdjęcie | `lithophane` — płaski, wygięty, cylinder (lampka), kolorowy CMY | bez AI |

Chmura używa darmowych GPU na Hugging Face Spaces. Bywają kolejki i dzienny limit. Darmowy token HF (`--hf-token` albo zmienna `HF_TOKEN`) zwiększa limit.

### Przygotowanie do druku (model 3D)
- naprawa siatki, usuwanie odłamków, wygładzanie, skalowanie do wysokości w mm
- ścięcie spodu na płaską podstawę (`--base-cut-mm`) albo podstawka z napisem (`--pedestal-text "Tomasz 2026"`)
- **wydrążanie** z zadaną grubością ścianki i otworem odpływowym w najniższym punkcie wnęki (`--hollow-mm 2 --drain-mm 4`)
- **automatyczna orientacja** minimalizująca nawisy i podpory (`--auto-orient`)
- **podział** dużych modeli na części mieszczące się na stole, z otworami na kołki i gotowym kołkiem do druku (`--split --bed-x 220 --bed-y 220 --bed-z 250`)

### Płaskorzeźby i breloki
- kształty: prostokąt, zaokrąglony, koło, owal, sześciokąt, serce albo **kontur obiektu** (`--shape contour`)
- ramka (`--frame-mm`), **brelok z oczkiem** (`--keychain`), **napis grawerowany na spodzie** (`--back-text`)

### Kolor
- `--color` daje **3MF z pomalowanymi trójkątami** pod AMS/MMU (PrusaSlicer, OrcaSlicer, Bambu Studio), kolory zredukowane do `--n-colors` filamentów, plus GLB z kolorami.
- Kolorowy litofan (`--litho color`) to 4 części (biały + cyan + magenta + żółty). Przy wczytaniu 3MF slicer zapyta o złożenie w jeden obiekt — odpowiedz „tak” i przypisz filamenty.

### Po wygenerowaniu
- **G-code** przez PrusaSlicer albo OrcaSlicer w trybie wiersza poleceń (`--slice --slicer-config profil.ini`)
- **wysyłka do drukarki**: OctoPrint albo Klipper/Moonraker (`--printer-url http://192.168.1.50 --printer-key …`), opcjonalnie z od razu rozpoczętym drukiem (`--start-print`)
- **historia** wszystkich modeli z miniaturami i porównaniem dwóch wersji obok siebie (zakładka „Historia” albo `--history`)
- **powiadomienie MQTT** po każdym modelu (`--mqtt adres-brokera`)

## Przykłady z wiersza poleceń

```bash
python foto2stl.py kubek.jpg -m full3d --engine hunyuan3d --height-mm 90 --auto-orient
python foto2stl.py figurka.jpg -m full3d --hollow-mm 2 --drain-mm 4 --pedestal-text "Dla Ani"
python foto2stl.py --prompt "a cute robot owl figurine" -m text3d --engine hunyuan3d
python foto2stl.py -m multiview --front przod.jpg --back tyl.jpg --left lewo.jpg
python foto2stl.py pies.jpg -m relief --shape contour --remove-bg --keychain --width-mm 45 --relief-mm 3 --back-text "Burek"
python foto2stl.py foto.jpg -m lithophane --litho cylinder --width-mm 250     # obwód lampki 250 mm
python foto2stl.py foto.jpg -m lithophane --shape heart --frame-mm 3
python foto2stl.py logo.png -m heightmap --color --formats 3mf --n-colors 3
python foto2stl.py smok.jpg -m full3d --height-mm 400 --split --bed-x 256 --bed-y 256 --bed-z 256
python foto2stl.py kot.jpg -m relief --slice --slicer-config moja_drukarka.ini --printer-url http://octopi.local --printer-key ABC
python foto2stl.py --help        # wszystkie opcje
```

## Serwer na Raspberry Pi

```bash
bash install.sh --pi
bash start.sh --server --watch ~/foto2stl-inbox --mqtt localhost --engine hunyuan3d
```

- GUI w sieci: `http://<adres-pi>:7860`
- REST, np. z uConsole:
  `curl -F image=@zdjecie.jpg -F mode=relief http://pi.local:7860/api/convert -o model.stl`
  `curl -F prompt="cute robot owl" -F mode=text3d -F 'options={"engine":"hunyuan3d"}' http://pi.local:7860/api/convert -o model.zip`
- katalog obserwowany: wrzuć zdjęcie (scp, Syncthing, Samba) do `~/foto2stl-inbox`, a STL pojawi się w `wyniki/`. Plik `.txt` z opisem uruchamia tryb text3d.
- autostart: `foto2stl.service` (instrukcja w środku pliku). MQTT publikuje na `foto2stl/done` JSON z nazwami plików i raportem.

Na Pi 4 i uConsole (CM4) sensownie działają tryby płaskie, relief i silniki chmurowe. Lokalny TripoSR potrzebuje ok. 4 GB RAM przy `--mc-res 128` i 5 GB przy domyślnym 256 (zmierzone na CPU), a na Cortex-A72 liczy kilka minut — z modułem 4 GB tylko z `--mc-res 128` i swapem, lepiej `--engine hunyuan3d`.

- System musi być 64-bitowy (`uname -m` → `aarch64`); na czystym Debianie najpierw `sudo apt install python3-venv python3-dev git`.
- Usuwanie tła (rembg) domyślnie używa `u2net` (176 MB). Najlżejszy: `--rembg-model u2netp` (5 MB). Pierwsze uruchomienie rembg kompiluje moduły (numba) — na ARM potrafi to trwać kilka minut, potem już nie.
- Opcje podane przy `--server` (np. `--engine`, `--hf-token`, `--mqtt`, `--depth-model`) obowiązują też w GUI; ustawienia wybrane w interfejsie mają pierwszeństwo.

## Dobre zdjęcia do 3D
- jeden obiekt, cały w kadrze, lekko z góry (15–30°), jednolite tło, rozproszone światło
- przezroczyste i lustrzane obiekty wychodzą słabo
- obiekt leży krzywo? `--rotate-x 90`. Dziury? obniż `--mc-threshold` (np. 15).
- kontrola wycięcia tła dla TripoSR: `--debug-dir .`

## Rozwiązywanie problemów
- **Silnik chmurowy zwraca błąd endpointu**: autorzy Space'a zmienili API. Sprawdź `python foto2stl.py --cloud-api tencent/Hunyuan3D-2` (pokazuje parametry z wartościami domyślnymi i oznacza endpointy, których przycisk jest ukryty w interfejsie) i dopasuj profil w `foto2stl/cloud.py` → `ENGINES` albo flagami `--space`, `--space-api`, `--space-image-param` (działają z dowolnym Space'em image→3D).
- **Kolor z Hunyuan3D-2 (`--color` / `hunyuan3d-color`)**: publiczny Space ma obecnie wyłączone generowanie tekstur („Texture Generation (Unavailable)”). Program wykrywa to (albo błąd tekstur) i generuje sam kształt, bez koloru, zamiast tracić limit GPU.
- **`transformers` a TripoSR**: TripoSR był pisany pod `transformers==4.35`, a transformers 5 zmienił nazwy wag enkodera ViT. Foto2STL tłumaczy je przy wczytywaniu, więc działa z obiema wersjami; gdyby kolejna wersja znów coś zmieniła, komunikat podpowie `pip install "transformers<5"`.
- **Malowanie 3MF** jest odczytywane przez PrusaSlicer, OrcaSlicer i Bambu Studio. Gdyby kolory się nie pojawiły, wczytaj GLB albo użyj wielu części.
- **Licencje**: Foto2STL — MIT (plik `LICENSE`). Modele: TripoSR (MIT), Depth Anything V2 Small (Apache-2.0), rembg u2net (Apache-2.0); większe warianty Depth Anything i modele w Space'ach mają własne licencje, sprawdź przed użyciem komercyjnym.
