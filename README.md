# Foto2STL 2.0

Zdjęcie, kilka zdjęć albo sam opis → model gotowy do druku 3D. Lokalna i darmowa alternatywa dla Meshy.

## Szybki start

**Windows:** uruchom `install.bat`, potem `start.bat` (otworzy się przeglądarka).
**Linux / macOS:** `./install.sh`, potem `./start.sh`.
**Raspberry Pi:** `./install.sh --pi`, potem `./start.sh --server` (szczegóły niżej).

Bez instalacji Pythona: `python build_exe.py --lite` zbuduje folder z `Foto2STL.exe` (dwuklik = GUI).

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
./install.sh --pi
./start.sh --server --watch ~/foto2stl-inbox --mqtt localhost --engine hunyuan3d
```

- GUI w sieci: `http://<adres-pi>:7860`
- REST, np. z uConsole:
  `curl -F image=@zdjecie.jpg -F mode=relief http://pi.local:7860/api/convert -o model.stl`
  `curl -F prompt="cute robot owl" -F mode=text3d -F 'options={"engine":"hunyuan3d"}' http://pi.local:7860/api/convert -o model.zip`
- katalog obserwowany: wrzuć zdjęcie (scp, Syncthing, Samba) do `~/foto2stl-inbox`, a STL pojawi się w `wyniki/`. Plik `.txt` z opisem uruchamia tryb text3d.
- autostart: `foto2stl.service` (instrukcja w środku pliku). MQTT publikuje na `foto2stl/done` JSON z nazwami plików i raportem.

Na Pi 4 sensownie działają tryby płaskie i silniki chmurowe. Lokalny TripoSR jest za ciężki.

## Dobre zdjęcia do 3D
- jeden obiekt, cały w kadrze, lekko z góry (15–30°), jednolite tło, rozproszone światło
- przezroczyste i lustrzane obiekty wychodzą słabo
- obiekt leży krzywo? `--rotate-x 90`. Dziury? obniż `--mc-threshold` (np. 15).
- kontrola wycięcia tła dla TripoSR: `--debug-dir .`

## Rozwiązywanie problemów
- **Silnik chmurowy zwraca błąd endpointu**: autorzy Space'a zmienili API. Sprawdź `python foto2stl.py --cloud-api tencent/Hunyuan3D-2` i dopasuj (`--space`, `--space-api`, `--space-image-param` działają z dowolnym Space'em image→3D).
- **`transformers` a TripoSR**: TripoSR był pisany pod `transformers==4.35`. Jeśli `full3d` lokalnie rzuca błędem, zrób osobne venv z tą wersją albo użyj silnika chmurowego.
- **Malowanie 3MF** jest odczytywane przez PrusaSlicer, OrcaSlicer i Bambu Studio. Gdyby kolory się nie pojawiły, wczytaj GLB albo użyj wielu części.
- **Licencje**: TripoSR (MIT), Depth Anything V2 Small (Apache-2.0); większe warianty Depth Anything i modele w Space'ach mają własne licencje, sprawdź przed użyciem komercyjnym.
