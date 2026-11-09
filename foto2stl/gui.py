"""Interfejs w przeglądarce (Gradio): zdjęcie / tekst / wiele widoków → 3D, historia i porównanie."""
from __future__ import annotations

import threading
import traceback

from . import history
from .pipeline import options, run

LOCK = threading.Lock()  # modele AI liczą jedno zadanie naraz

ENGINE_CHOICES = [("Lokalnie – TripoSR (CPU/GPU)", "local"),
                  ("Chmura – Hunyuan3D-2 (najlepsza jakość)", "hunyuan3d"),
                  ("Chmura – Hunyuan3D-2 z teksturą (kolor)", "hunyuan3d-color")]
MODE_CHOICES = [("Pełne 3D", "full3d"), ("Płaskorzeźba (AI)", "relief"),
                ("Mapa jasności", "heightmap"), ("Litofan", "lithophane")]
SHAPES = [("Prostokąt", "rect"), ("Zaokrąglony", "rounded"), ("Koło", "circle"), ("Owal", "oval"),
          ("Sześciokąt", "hexagon"), ("Serce", "heart"), ("Kontur obiektu", "contour")]
LITHO = [("Płaski", "flat"), ("Wygięty", "curved"), ("Cylinder (lampka)", "cylinder"),
         ("Kolorowy CMY (AMS/MMU)", "color")]

CSS = """
.gradio-container {max-width: 1280px !important}
#go-photo, #go-text, #go-mv {min-height: 48px; font-size: 1.05rem}
"""


def _gr_major():
    import gradio as gr
    return int(gr.__version__.split(".")[0])


def build_ui(base_opts=None):
    """base_opts: opcje z wiersza poleceń (np. --engine, --hf-token, --depth-model, --mqtt) — obowiązują
    w GUI tak jak w REST; to, co użytkownik ustawi w interfejsie, ma pierwszeństwo."""
    import gradio as gr

    base = {k: v for k, v in (base_opts or {}).items() if v is not None}
    S = {}  # ustawienia wspólne dla wszystkich zakładek
    bkw = {} if _gr_major() >= 6 else dict(css=CSS, theme=gr.themes.Soft())

    with gr.Blocks(title="Foto2STL", **bkw) as ui:
        gr.Markdown("# Foto2STL\nZdjęcie albo opis → model gotowy do druku 3D.")
        with gr.Row(equal_height=False):
            with gr.Column(scale=5):
                with gr.Tabs():
                    with gr.Tab("Ze zdjęcia"):
                        image = gr.Image(type="filepath", label="Zdjęcie (plik, kamerka lub schowek)",
                                         sources=["upload", "webcam", "clipboard"], height=300)
                        mode = gr.Radio(MODE_CHOICES, value="relief", label="Co zrobić")
                        go_photo = gr.Button("Generuj model", variant="primary", elem_id="go-photo")
                    with gr.Tab("Z opisu"):
                        prompt = gr.Textbox(value="", label="Opis obiektu (najlepiej po angielsku)", lines=3,
                                            placeholder="a cute robot owl figurine with big round eyes")
                        gr.Markdown("Obraz powstaje w chmurze (FLUX), a model 3D wybranym silnikiem.")
                        go_text = gr.Button("Generuj z opisu", variant="primary", elem_id="go-text")
                    with gr.Tab("Z kilku zdjęć"):
                        gr.Markdown("Ten sam obiekt z kilku stron — tył przestaje być zgadywany "
                                    "(chmura: Hunyuan3D-2mv). Wystarczy przód + dowolne inne.")
                        with gr.Row():
                            front = gr.Image(type="filepath", label="Przód", height=170)
                            back = gr.Image(type="filepath", label="Tył", height=170)
                        with gr.Row():
                            left = gr.Image(type="filepath", label="Lewa strona", height=170)
                            right = gr.Image(type="filepath", label="Prawa strona", height=170)
                        go_mv = gr.Button("Generuj z wielu widoków", variant="primary", elem_id="go-mv")
                    with gr.Tab("Historia"):
                        refresh = gr.Button("Odśwież")
                        gallery = gr.Gallery(label="Ostatnie modele", columns=4, height=260, allow_preview=False)
                        with gr.Row():
                            pick_a = gr.Dropdown(label="Model A", choices=[])
                            pick_b = gr.Dropdown(label="Model B (porównanie)", choices=[])
                        with gr.Row():
                            view_a = gr.Model3D(label="A", height=320)
                            view_b = gr.Model3D(label="B", height=320)
                        hist_info = gr.Textbox(value="", label="Szczegóły", lines=4)

                with gr.Accordion("Rozmiar i kształt", open=True):
                    S["width_mm"] = gr.Slider(10, 300, 100, step=1, label="Szerokość – tryby płaskie / obwód cylindra [mm]")
                    S["height_mm"] = gr.Slider(10, 400, 33, step=1, label="Wysokość modelu 3D [mm] (33 = skala modelarska)")
                    S["shape"] = gr.Dropdown(SHAPES, value="rect", label="Kształt płaskorzeźby / litofanu")
                    with gr.Row():
                        S["relief_mm"] = gr.Slider(0.5, 30, 6, step=0.5, label="Głębokość reliefu [mm]")
                        S["base_mm"] = gr.Slider(0.4, 10, 2, step=0.2, label="Podstawa [mm]")
                    with gr.Row():
                        S["frame_mm"] = gr.Slider(0, 10, 0, step=0.5, label="Ramka [mm]")
                        S["remove_bg"] = gr.Checkbox(False, label="Usuń tło")
                        S["invert"] = gr.Checkbox(False, label="Odwróć wysokości")
                with gr.Accordion("Brelok i napisy", open=False):
                    S["keychain"] = gr.Checkbox(False, label="Zrób brelok (oczko na kółko)")
                    S["back_text"] = gr.Textbox(value="", label="Napis grawerowany na spodzie")
                    S["pedestal_text"] = gr.Textbox(value="", label="Podstawka z napisem pod model 3D (pusty = bez napisu)")
                    S["pedestal"] = gr.Checkbox(False, label="Dodaj podstawkę pod model 3D")
                with gr.Accordion("Litofan", open=False):
                    S["litho"] = gr.Radio(LITHO, value="flat", label="Rodzaj")
                    with gr.Row():
                        S["min_mm"] = gr.Slider(0.4, 2, 0.8, step=0.1, label="Min. grubość [mm]")
                        S["max_mm"] = gr.Slider(1.5, 6, 3.0, step=0.1, label="Maks. grubość [mm]")
                    S["arc_deg"] = gr.Slider(30, 300, 120, step=5, label="Kąt wygięcia [°]")
                with gr.Accordion("Model 3D i druk", open=False):
                    engines = [v for _, v in ENGINE_CHOICES]
                    S["engine"] = gr.Dropdown(ENGINE_CHOICES, label="Silnik 3D",
                                              value=base.get("engine") if base.get("engine") in engines else "local")
                    with gr.Row():
                        S["mc_res"] = gr.Slider(128, 384, 256, step=32, label="Szczegółowość (lokalnie)")
                        S["smooth_iters"] = gr.Slider(0, 30, 5, step=1, label="Wygładzanie")
                    with gr.Row():
                        S["base_cut_mm"] = gr.Slider(0, 20, 0, step=0.5, label="Ścięcie spodu [mm]")
                        S["rotate_x"] = gr.Slider(-180, 180, 0, step=90, label="Obrót X [°]")
                    with gr.Row():
                        S["hollow_mm"] = gr.Slider(0, 6, 0, step=0.5, label="Wydrążenie – ścianka [mm] (0 = pełny)")
                        S["drain_mm"] = gr.Slider(0, 10, 0, step=0.5, label="Otwór odpływowy Ø [mm]")
                    S["auto_orient"] = gr.Checkbox(False, label="Automatyczna orientacja (mniej podpór)")
                    S["split"] = gr.Checkbox(False, label="Podziel na części, jeśli nie mieści się na stole")
                    with gr.Row():
                        S["bed_x"] = gr.Number(220, label="Stół X [mm]")
                        S["bed_y"] = gr.Number(220, label="Stół Y [mm]")
                        S["bed_z"] = gr.Number(250, label="Wys. Z [mm]")
                with gr.Accordion("Kolor i eksport", open=False):
                    S["color"] = gr.Checkbox(False, label="Kolor (3MF z malowaniem pod AMS/MMU + GLB)")
                    S["n_colors"] = gr.Slider(2, 8, 4, step=1, label="Liczba filamentów")
                    S["formats"] = gr.CheckboxGroup(["3mf", "glb", "ply", "obj"], value=[], label="Dodatkowe formaty")
                with gr.Accordion("Slicer i drukarka", open=False):
                    S["slice"] = gr.Checkbox(False, label="Pokrój do G-code")
                    S["slicer_config"] = gr.Textbox(value="", label="Plik ustawień (.ini PrusaSlicer lub maszyna.json;proces.json Orca)")
                    S["slicer_filament"] = gr.Textbox(value="", label="Filament .json (tylko OrcaSlicer)")
                    S["printer_kind"] = gr.Radio([("OctoPrint", "octoprint"), ("Klipper / Moonraker", "moonraker")],
                                                 value="octoprint", label="Drukarka")
                    S["printer_url"] = gr.Textbox(value="", label="Adres drukarki (np. http://192.168.1.50)")
                    S["printer_key"] = gr.Textbox(value="", label="Klucz API", type="password")
                    S["start_print"] = gr.Checkbox(False, label="Od razu zacznij drukować")

            with gr.Column(scale=4):
                view = gr.Model3D(label="Podgląd", height=460, clear_color=[0.92, 0.93, 0.95, 1.0])
                files = gr.File(label="Pliki do pobrania", file_count="multiple")
                info = gr.Textbox(value="", label="Raport", lines=6)
                used_image = gr.Image(label="Obraz użyty do generowania", height=200, visible=False)

        keys = list(S)

        def collect(vals):
            kw = dict(zip(keys, vals))
            kw["formats"] = ",".join(["stl"] + list(kw.get("formats") or []))
            for k in ("slicer_config", "slicer_filament", "printer_url", "printer_key"):
                kw[k] = kw.get(k) or base.get(k)
            return options(**{**base, **kw})

        def job(mode, inputs, vals):
            if not LOCK.acquire(timeout=1):
                raise gr.Error("Trwa inne generowanie — poczekaj chwilę.")
            try:
                r = run(mode, inputs, collect(vals))
            except Exception as e:  # noqa: BLE001
                traceback.print_exc()
                raise gr.Error(str(e)) from e
            finally:
                LOCK.release()
            img = inputs.get("image") if mode == "text3d" else None
            return (r["preview"], r["files"], r["report"] + (f"\nG-code: {r['gcode']}" if r["gcode"] else ""),
                    gr.update(value=img, visible=img is not None))

        def from_photo(img, m, *vals):
            if not img:
                raise gr.Error("Najpierw dodaj zdjęcie.")
            return job(m, {"image": img}, vals)

        def from_text(p, *vals):
            return job("text3d", {"prompt": p}, vals)

        def from_views(f, b, l, r, *vals):
            if not f:
                raise gr.Error("Dodaj co najmniej zdjęcie z przodu.")
            return job("multiview", {"front": f, "back": b, "left": l, "right": r}, vals)

        outs = [view, files, info, used_image]
        sv = list(S.values())
        go_photo.click(from_photo, [image, mode, *sv], outs, api_name="photo")
        go_text.click(from_text, [prompt, *sv], outs, api_name="text")
        go_mv.click(from_views, [front, back, left, right, *sv], outs, api_name="multiview")

        def load_hist():
            ents = history.entries()
            gal = [(e["thumb"], f"{e['time']} · {e['mode']}") for e in ents if e["thumb"]]
            ch = [(f"{e['time']} · {e['mode']} {e.get('label', '')[:30]}", e["dir"]) for e in ents if e["preview"]]
            return gal, gr.update(choices=ch), gr.update(choices=ch)

        def show(d):
            e = next((x for x in history.entries() if x["dir"] == d), None)
            if not e:
                return None, ""
            return e["preview"], f"{e['time']} · {e['mode']}\n{e['report']}\nFolder: {e['dir']}"

        refresh.click(load_hist, None, [gallery, pick_a, pick_b])
        ui.load(load_hist, None, [gallery, pick_a, pick_b])
        pick_a.change(show, pick_a, [view_a, hist_info])
        pick_b.change(lambda d: show(d)[0], pick_b, view_b)
    return ui


def run_gui(host="127.0.0.1", port=7860, share=False, base_opts=None):
    import gradio as gr
    ui = build_ui(base_opts)
    kw = dict(server_name=host, server_port=port, share=share, inbrowser=host in ("127.0.0.1", "localhost"))
    if _gr_major() >= 6:
        kw.update(css=CSS, theme=gr.themes.Soft())
    ui.queue().launch(**kw)
