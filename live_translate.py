#!/usr/bin/env python3
"""Live screen-region translator.

Drag-select any part of your screen and this tool continuously reads the text
in that region and paints a live translation *directly on top of the original
text*, so the source text is covered by its translation.

Pipeline:  screen capture (mss) -> change detection -> OCR (EasyOCR) ->
translation (deep-translator / Google Translate) -> in-place overlay (Tkinter).

To keep things efficient the region is only re-OCR'd when the pixels actually
change (checked every ~2 s by default).

Run ``python live_translate.py`` to open the control panel, or
``python live_translate.py --help`` for options.
"""

from __future__ import annotations

import argparse
import queue
import sys
import threading
import time
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Optional


# --------------------------------------------------------------------------- #
# Language tables
# --------------------------------------------------------------------------- #
# "tr" is the Google Translate code; "ocr" is the matching EasyOCR language
# code (None => EasyOCR can't read this script, so it's a translation *target*
# only and OCR falls back to English for it).
LANGUAGES: dict[str, dict[str, Optional[str]]] = {
    # display name           : {"tr": translate-code, "ocr": easyocr-code}
    "Auto-detect":            {"tr": "auto",  "ocr": None},
    "English":                {"tr": "en",    "ocr": "en"},
    "Spanish":                {"tr": "es",    "ocr": "es"},
    "French":                 {"tr": "fr",    "ocr": "fr"},
    "German":                 {"tr": "de",    "ocr": "de"},
    "Italian":                {"tr": "it",    "ocr": "it"},
    "Portuguese":             {"tr": "pt",    "ocr": "pt"},
    "Dutch":                  {"tr": "nl",    "ocr": "nl"},
    "Russian":                {"tr": "ru",    "ocr": "ru"},
    "Japanese":               {"tr": "ja",    "ocr": "ja"},
    "Korean":                 {"tr": "ko",    "ocr": "ko"},
    "Chinese (Simplified)":   {"tr": "zh-CN", "ocr": "ch_sim"},
    "Chinese (Traditional)":  {"tr": "zh-TW", "ocr": "ch_tra"},
    "Arabic":                 {"tr": "ar",    "ocr": "ar"},
    "Hindi":                  {"tr": "hi",    "ocr": "hi"},
    "Turkish":                {"tr": "tr",    "ocr": "tr"},
    "Polish":                 {"tr": "pl",    "ocr": "pl"},
    "Vietnamese":             {"tr": "vi",    "ocr": "vi"},
    "Thai":                   {"tr": "th",    "ocr": "th"},
    "Ukrainian":              {"tr": "uk",    "ocr": "uk"},
    "Indonesian":             {"tr": "id",    "ocr": "id"},
    "Greek":                  {"tr": "el",    "ocr": None},
    "Hebrew":                 {"tr": "he",    "ocr": None},
}

DEFAULT_SOURCE = "Auto-detect"
DEFAULT_TARGET = "English"
DEFAULT_INTERVAL = 2.0    # seconds between capture passes (requirement: ~2 s)
CAPTURE_DELAY_MS = 90     # let the overlay disappear before we screenshot
DIFF_THRESHOLD = 4.0      # mean per-pixel grey delta that counts as "changed"


# --------------------------------------------------------------------------- #
# Dependency handling
# --------------------------------------------------------------------------- #
class MissingDependency(RuntimeError):
    """Raised when an optional runtime dependency is not installed."""


def _require(module: str, pip_name: str):
    try:
        return __import__(module)
    except ImportError as exc:  # pragma: no cover - env dependent
        raise MissingDependency(
            f"Missing dependency '{pip_name}'. Install it with:\n"
            f"    pip install {pip_name}"
        ) from exc


# --------------------------------------------------------------------------- #
# Screen capture
# --------------------------------------------------------------------------- #
def screenshot_rgb(bbox: "Region"):
    """Return an (H, W, 3) uint8 RGB numpy array of the given screen region."""
    mss = _require("mss", "mss")
    np = _require("numpy", "numpy")

    monitor = {"left": bbox.x, "top": bbox.y, "width": bbox.w, "height": bbox.h}
    with mss.mss() as sct:
        shot = sct.grab(monitor)
    arr = np.frombuffer(shot.bgra, dtype=np.uint8).reshape(shot.height, shot.width, 4)
    return arr[:, :, [2, 1, 0]].copy()  # BGRA -> RGB


def thumbnail(rgb):
    """Small grayscale signature used for cheap change detection."""
    np = _require("numpy", "numpy")
    # Downsample by striding, then average channels -> ~grayscale.
    step_y = max(1, rgb.shape[0] // 54)
    step_x = max(1, rgb.shape[1] // 96)
    small = rgb[::step_y, ::step_x].astype(np.int16)
    return small.mean(axis=2)


def images_differ(prev_thumb, new_thumb) -> bool:
    if prev_thumb is None:
        return True
    np = _require("numpy", "numpy")
    if prev_thumb.shape != new_thumb.shape:
        return True
    return float(np.mean(np.abs(prev_thumb - new_thumb))) > DIFF_THRESHOLD


# --------------------------------------------------------------------------- #
# Translation
# --------------------------------------------------------------------------- #
class Translator:
    """Thin cached wrapper around deep-translator's GoogleTranslator."""

    @staticmethod
    @lru_cache(maxsize=1024)
    def translate(text: str, source: str, target: str) -> str:
        if not text.strip():
            return ""
        deep = _require("deep_translator", "deep-translator")
        from deep_translator import GoogleTranslator

        try:
            return GoogleTranslator(source=source, target=target).translate(text)
        except Exception as exc:  # network / API hiccup - keep the app alive
            return f"[{exc}]"


# --------------------------------------------------------------------------- #
# OCR (EasyOCR)
# --------------------------------------------------------------------------- #
class OcrEngine:
    """Lazily-built EasyOCR reader, rebuilt when the source language changes."""

    def __init__(self):
        self._reader = None
        self._langs: tuple[str, ...] = ()

    def _build(self, langs: tuple[str, ...]):
        easyocr = _require("easyocr", "easyocr")
        try:
            return easyocr.Reader(list(langs), gpu=False, verbose=False)
        except Exception:
            # Some scripts must be paired with English; then fall back to English.
            fallback = list(langs) + (["en"] if "en" not in langs else [])
            try:
                return easyocr.Reader(fallback, gpu=False, verbose=False)
            except Exception:
                return easyocr.Reader(["en"], gpu=False, verbose=False)

    def read(self, rgb, langs: tuple[str, ...]):
        """Return EasyOCR detections: list of (bbox_points, text, confidence)."""
        if langs != self._langs or self._reader is None:
            self._reader = self._build(langs)
            self._langs = langs
        return self._reader.readtext(rgb)


# --------------------------------------------------------------------------- #
# Colour helpers (for painting translations that blend with the background)
# --------------------------------------------------------------------------- #
def _hex(rgb) -> str:
    return "#%02x%02x%02x" % (int(rgb[0]), int(rgb[1]), int(rgb[2]))


def _readable_fg(rgb) -> str:
    lum = 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]
    return "#000000" if lum > 140 else "#ffffff"


# --------------------------------------------------------------------------- #
# Data types
# --------------------------------------------------------------------------- #
@dataclass
class Region:
    x: int
    y: int
    w: int
    h: int

    def valid(self) -> bool:
        return self.w > 4 and self.h > 4


@dataclass
class Box:
    """A translated text box positioned relative to the region's top-left."""
    left: int
    top: int
    width: int
    height: int
    text: str
    bg: str
    fg: str


@dataclass
class Settings:
    source_name: str = DEFAULT_SOURCE
    target_name: str = DEFAULT_TARGET
    interval: float = DEFAULT_INTERVAL
    region: Optional[Region] = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def snapshot(self) -> "Settings":
        with self._lock:
            return Settings(
                self.source_name, self.target_name, self.interval, self.region
            )

    def update(self, **kwargs):
        with self._lock:
            for key, value in kwargs.items():
                setattr(self, key, value)


def ocr_langs_for(source_name: str) -> tuple[str, ...]:
    """EasyOCR language tuple for a source selection (falls back to English)."""
    code = LANGUAGES[source_name]["ocr"]
    return (code,) if code else ("en",)


# --------------------------------------------------------------------------- #
# Tkinter UI
# --------------------------------------------------------------------------- #
def run_gui(initial: Settings):
    try:
        import tkinter as tk
        from tkinter import ttk, font as tkfont
    except ImportError as exc:
        raise MissingDependency(
            "Tkinter is not available. It normally ships with Python, but "
            "some systems need it separately:\n"
            "  Ubuntu/Debian:  sudo apt install python3-tk\n"
            "  Fedora:         sudo dnf install python3-tkinter\n"
            "  macOS (brew):   brew install python-tk"
        ) from exc

    settings = initial

    # Cross-thread channels.
    job_queue: "queue.Queue" = queue.Queue(maxsize=1)   # main -> worker (images)
    result_queue: "queue.Queue" = queue.Queue()          # worker -> main (boxes)

    state = {
        "running": False,
        "ocr_busy": False,
        "prev_thumb": None,
        "after_id": None,
    }

    root = tk.Tk()
    root.title("Live Screen Translator")
    root.geometry("400x300")
    root.resizable(False, False)

    # ------------------------------------------------------------------ #
    # Region selection overlay
    # ------------------------------------------------------------------ #
    def select_region():
        overlay = tk.Toplevel(root)
        overlay.attributes("-fullscreen", True)
        overlay.attributes("-alpha", 0.25)
        overlay.attributes("-topmost", True)
        overlay.configure(bg="black")
        overlay.config(cursor="crosshair")

        canvas = tk.Canvas(overlay, cursor="crosshair", bg="black",
                           highlightthickness=0)
        canvas.pack(fill="both", expand=True)
        canvas.create_text(
            overlay.winfo_screenwidth() // 2, 40,
            text="Drag to select the text region  ·  Esc to cancel",
            fill="white", font=("Helvetica", 18),
        )

        sel = {"x0": 0, "y0": 0, "rect": None}

        def on_press(event):
            sel["x0"], sel["y0"] = event.x_root, event.y_root
            sel["rect"] = canvas.create_rectangle(
                event.x, event.y, event.x, event.y, outline="#00e5ff", width=2)

        def on_drag(event):
            if sel["rect"] is not None:
                x0 = sel["x0"] - overlay.winfo_rootx()
                y0 = sel["y0"] - overlay.winfo_rooty()
                canvas.coords(sel["rect"], x0, y0, event.x, event.y)

        def on_release(event):
            x0, y0, x1, y1 = sel["x0"], sel["y0"], event.x_root, event.y_root
            region = Region(min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0))
            overlay.destroy()
            if region.valid():
                settings.update(region=region)
                region_var.set(f"Region: {region.w}×{region.h} @ "
                              f"({region.x},{region.y})")
                start_btn.config(state="normal")

        canvas.bind("<ButtonPress-1>", on_press)
        canvas.bind("<B1-Motion>", on_drag)
        canvas.bind("<ButtonRelease-1>", on_release)
        overlay.bind("<Escape>", lambda _e: overlay.destroy())
        overlay.focus_force()

    # ------------------------------------------------------------------ #
    # In-place translation overlay (covers the region)
    # ------------------------------------------------------------------ #
    overlay = {"win": None, "frame": None, "labels": []}

    def create_overlay(region: Region):
        win = tk.Toplevel(root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.geometry(f"{region.w}x{region.h}+{region.x}+{region.y}")
        frame = tk.Frame(win, bg="#000000", width=region.w, height=region.h)
        frame.pack(fill="both", expand=True)
        frame.pack_propagate(False)
        overlay["win"], overlay["frame"], overlay["labels"] = win, frame, []
        win.withdraw()

    def hide_overlay():
        if overlay["win"] is not None:
            overlay["win"].withdraw()

    def show_overlay():
        if overlay["win"] is not None:
            overlay["win"].deiconify()
            overlay["win"].lift()
            overlay["win"].attributes("-topmost", True)

    def destroy_overlay():
        if overlay["win"] is not None:
            overlay["win"].destroy()
            overlay["win"] = overlay["frame"] = None
            overlay["labels"] = []

    def render_overlay(boxes: "list[Box]", panel_bg: str):
        frame = overlay["frame"]
        if frame is None:
            return
        for lbl in overlay["labels"]:
            lbl.destroy()
        overlay["labels"] = []
        frame.configure(bg=panel_bg)
        for box in boxes:
            size = max(8, min(48, int(box.height * 0.62)))
            lbl = tk.Label(
                frame, text=box.text, bg=box.bg, fg=box.fg,
                font=tkfont.Font(family="Helvetica", size=size),
                justify="left", anchor="nw", wraplength=max(40, box.width),
            )
            lbl.place(x=box.left, y=box.top, width=box.width, height=box.height)
            overlay["labels"].append(lbl)

    # ------------------------------------------------------------------ #
    # Worker thread: EasyOCR + translation
    # ------------------------------------------------------------------ #
    def worker():
        np = _require("numpy", "numpy")
        engine = OcrEngine()
        loaded = False
        while True:
            job = job_queue.get()
            if job is None:
                break
            rgb, ocr_langs, src_tr, tgt_tr = job
            try:
                if not loaded:
                    result_queue.put({"status": "Loading OCR model (first run "
                                     "downloads it)…"})
                detections = engine.read(rgb, ocr_langs)
                loaded = True
            except MissingDependency as exc:
                result_queue.put({"error": str(exc), "fatal": True})
                continue
            except Exception as exc:
                result_queue.put({"error": f"OCR failed: {exc}"})
                continue

            h, w = rgb.shape[0], rgb.shape[1]
            boxes: list[Box] = []
            for bbox, text, conf in detections:
                if conf < 0.3 or not text.strip():
                    continue
                xs = [p[0] for p in bbox]
                ys = [p[1] for p in bbox]
                left = max(0, int(min(xs)))
                top = max(0, int(min(ys)))
                right = min(w, int(max(xs)))
                bottom = min(h, int(max(ys)))
                bw, bh = max(1, right - left), max(1, bottom - top)
                translated = Translator.translate(text.strip(), src_tr, tgt_tr)
                crop = rgb[top:bottom, left:right].reshape(-1, 3)
                mean = crop.mean(axis=0) if crop.size else np.array([20, 20, 20])
                boxes.append(Box(left, top, bw, bh, translated,
                                 _hex(mean), _readable_fg(mean)))

            panel = rgb.reshape(-1, 3).mean(axis=0)
            result_queue.put({"boxes": boxes, "panel_bg": _hex(panel)})

    threading.Thread(target=worker, daemon=True).start()

    # ------------------------------------------------------------------ #
    # Capture loop (main thread), driven by root.after
    # ------------------------------------------------------------------ #
    def schedule_next():
        if state["running"]:
            interval = settings.snapshot().interval
            state["after_id"] = root.after(int(interval * 1000), tick)

    def tick():
        if not state["running"]:
            return
        hide_overlay()  # never OCR our own translation
        root.after(CAPTURE_DELAY_MS, capture_step)

    def capture_step():
        if not state["running"]:
            return
        cfg = settings.snapshot()
        try:
            rgb = screenshot_rgb(cfg.region)
        except MissingDependency as exc:
            status_var.set(str(exc).splitlines()[0])
            stop()
            return
        except Exception as exc:
            status_var.set(f"Capture failed: {exc}")
            show_overlay()
            schedule_next()
            return

        new_thumb = thumbnail(rgb)
        changed = images_differ(state["prev_thumb"], new_thumb)

        if changed and not state["ocr_busy"]:
            state["prev_thumb"] = new_thumb
            state["ocr_busy"] = True
            status_var.set(f"Text changed — translating…  "
                          f"({time.strftime('%H:%M:%S')})")
            job = (rgb, ocr_langs_for(cfg.source_name),
                   LANGUAGES[cfg.source_name]["tr"],
                   LANGUAGES[cfg.target_name]["tr"])
            try:
                job_queue.put_nowait(job)
            except queue.Full:
                state["ocr_busy"] = False
            # Leave the overlay hidden; it reappears once the result renders.
        else:
            show_overlay()  # unchanged -> just keep covering the original

        schedule_next()

    def poll_results():
        try:
            while True:
                msg = result_queue.get_nowait()
                if "status" in msg:
                    status_var.set(msg["status"])
                    continue
                if "error" in msg:
                    status_var.set("Error: " + msg["error"].splitlines()[0])
                    if msg.get("fatal"):
                        stop()
                    state["ocr_busy"] = False
                    show_overlay()
                    continue
                render_overlay(msg["boxes"], msg["panel_bg"])
                show_overlay()
                state["ocr_busy"] = False
                status_var.set(f"Covered {len(msg['boxes'])} text block(s)  "
                              f"({time.strftime('%H:%M:%S')})")
        except queue.Empty:
            pass
        root.after(120, poll_results)

    # ------------------------------------------------------------------ #
    # Start / stop
    # ------------------------------------------------------------------ #
    def start():
        cfg = settings.snapshot()
        if cfg.region is None:
            status_var.set("Select a region first.")
            return
        settings.update(
            source_name=source_var.get(),
            target_name=target_var.get(),
            interval=float(interval_var.get()),
        )
        state["prev_thumb"] = None
        state["ocr_busy"] = False
        destroy_overlay()
        create_overlay(settings.snapshot().region)
        state["running"] = True
        start_btn.config(state="disabled")
        stop_btn.config(state="normal")
        status_var.set("Running…")
        tick()

    def stop():
        state["running"] = False
        if state["after_id"] is not None:
            root.after_cancel(state["after_id"])
            state["after_id"] = None
        destroy_overlay()
        start_btn.config(state="normal")
        stop_btn.config(state="disabled")
        status_var.set("Stopped.")

    def on_close():
        state["running"] = False
        try:
            job_queue.put_nowait(None)
        except queue.Full:
            pass
        root.after(150, root.destroy)

    # ------------------------------------------------------------------ #
    # Layout
    # ------------------------------------------------------------------ #
    pad = {"padx": 8, "pady": 4}
    frm = ttk.Frame(root, padding=10)
    frm.pack(fill="both", expand=True)

    source_names = [n for n in LANGUAGES if LANGUAGES[n]["ocr"] or n == "Auto-detect"]
    target_names = [n for n in LANGUAGES if n != "Auto-detect"]

    ttk.Label(frm, text="Translate from:").grid(row=0, column=0, sticky="w", **pad)
    source_var = tk.StringVar(value=settings.source_name)
    ttk.Combobox(frm, textvariable=source_var, values=source_names,
                state="readonly", width=24).grid(row=0, column=1, **pad)

    ttk.Label(frm, text="Translate to:").grid(row=1, column=0, sticky="w", **pad)
    target_var = tk.StringVar(value=settings.target_name)
    ttk.Combobox(frm, textvariable=target_var, values=target_names,
                state="readonly", width=24).grid(row=1, column=1, **pad)

    ttk.Label(frm, text="Check every (sec):").grid(row=2, column=0, sticky="w", **pad)
    interval_var = tk.StringVar(value=str(settings.interval))
    ttk.Spinbox(frm, from_=0.5, to=15.0, increment=0.5, textvariable=interval_var,
               width=6).grid(row=2, column=1, sticky="w", **pad)

    region_var = tk.StringVar(value="Region: not selected")
    ttk.Label(frm, textvariable=region_var).grid(
        row=3, column=0, columnspan=2, sticky="w", **pad)

    btns = ttk.Frame(frm)
    btns.grid(row=4, column=0, columnspan=2, pady=8)
    ttk.Button(btns, text="Select region", command=select_region).grid(
        row=0, column=0, padx=4)
    start_btn = ttk.Button(btns, text="Start", command=start, state="disabled")
    start_btn.grid(row=0, column=1, padx=4)
    stop_btn = ttk.Button(btns, text="Stop", command=stop, state="disabled")
    stop_btn.grid(row=0, column=2, padx=4)

    status_var = tk.StringVar(value="Select a region to begin.")
    ttk.Label(frm, textvariable=status_var, foreground="#555",
             wraplength=360, justify="left").grid(
        row=5, column=0, columnspan=2, sticky="w", **pad)

    if settings.region is not None:
        region_var.set(f"Region: {settings.region.w}×{settings.region.h}")
        start_btn.config(state="normal")

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.after(120, poll_results)
    root.mainloop()


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Live screen-region translator: drag-select part of your "
                   "screen and see the translation painted over the original.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    source_choices = [n for n in LANGUAGES if LANGUAGES[n]["ocr"] or n == "Auto-detect"]
    parser.add_argument("--from", dest="source", default=DEFAULT_SOURCE,
                       choices=source_choices,
                       help="Source language (of the on-screen text).")
    parser.add_argument("--to", dest="target", default=DEFAULT_TARGET,
                       choices=[n for n in LANGUAGES if n != "Auto-detect"],
                       help="Target language (what to translate into).")
    parser.add_argument("--interval", type=float, default=DEFAULT_INTERVAL,
                       help="Seconds between capture/change-check passes.")
    parser.add_argument("--region", metavar="X,Y,W,H",
                       help="Skip the picker and use this region directly.")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    region = None
    if args.region:
        try:
            x, y, w, h = (int(v) for v in args.region.split(","))
            region = Region(x, y, w, h)
        except ValueError:
            print("--region must be X,Y,W,H (e.g. 100,100,600,200)",
                 file=sys.stderr)
            return 2

    settings = Settings(
        source_name=args.source,
        target_name=args.target,
        interval=args.interval,
        region=region,
    )
    try:
        run_gui(settings)
    except MissingDependency as exc:
        print(exc, file=sys.stderr)
        return 1
    except Exception as exc:  # e.g. no display available (headless machine)
        if "display" in str(exc).lower():
            print("No graphical display is available. This tool needs a "
                 "desktop (X11/Wayland/macOS/Windows) to run.", file=sys.stderr)
        else:
            print(f"Failed to start GUI: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
