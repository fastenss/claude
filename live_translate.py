#!/usr/bin/env python3
"""Live screen-region translator.

Drag-select any part of your screen and this tool will continuously OCR the
text in that region and show a live translation in a floating overlay.

Pipeline:  screen capture (mss)  ->  OCR (Tesseract)  ->  translation
(deep-translator / Google Translate)  ->  floating overlay (Tkinter).

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
# Translation codes are Google Translate codes; the OCR column is the matching
# Tesseract language-pack code (you must have that pack installed for good OCR).
LANGUAGES: dict[str, dict[str, str]] = {
    # display name : {"tr": translate-code, "ocr": tesseract-code}
    "Auto-detect":        {"tr": "auto",  "ocr": "eng"},
    "English":            {"tr": "en",    "ocr": "eng"},
    "Spanish":            {"tr": "es",    "ocr": "spa"},
    "French":             {"tr": "fr",    "ocr": "fra"},
    "German":             {"tr": "de",    "ocr": "deu"},
    "Italian":            {"tr": "it",    "ocr": "ita"},
    "Portuguese":         {"tr": "pt",    "ocr": "por"},
    "Dutch":              {"tr": "nl",    "ocr": "nld"},
    "Russian":            {"tr": "ru",    "ocr": "rus"},
    "Japanese":           {"tr": "ja",    "ocr": "jpn"},
    "Korean":             {"tr": "ko",    "ocr": "kor"},
    "Chinese (Simplified)": {"tr": "zh-CN", "ocr": "chi_sim"},
    "Chinese (Traditional)": {"tr": "zh-TW", "ocr": "chi_tra"},
    "Arabic":             {"tr": "ar",    "ocr": "ara"},
    "Hindi":              {"tr": "hi",    "ocr": "hin"},
    "Turkish":            {"tr": "tr",    "ocr": "tur"},
    "Polish":             {"tr": "pl",    "ocr": "pol"},
    "Vietnamese":         {"tr": "vi",    "ocr": "vie"},
    "Thai":               {"tr": "th",    "ocr": "tha"},
    "Ukrainian":          {"tr": "uk",    "ocr": "ukr"},
    "Greek":              {"tr": "el",    "ocr": "ell"},
    "Hebrew":             {"tr": "he",    "ocr": "heb"},
    "Indonesian":         {"tr": "id",    "ocr": "ind"},
}

DEFAULT_SOURCE = "Auto-detect"
DEFAULT_TARGET = "English"
DEFAULT_INTERVAL = 1.2  # seconds between capture passes


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
def grab_region(bbox: "Region"):
    """Return a PIL.Image of the given screen region using mss."""
    mss = _require("mss", "mss")
    _require("PIL", "Pillow")
    from PIL import Image as PILImage

    monitor = {
        "left": bbox.x,
        "top": bbox.y,
        "width": bbox.w,
        "height": bbox.h,
    }
    with mss.mss() as sct:
        shot = sct.grab(monitor)
        return PILImage.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")


# --------------------------------------------------------------------------- #
# OCR
# --------------------------------------------------------------------------- #
def ocr_image(image, tess_lang: str) -> str:
    """Extract text from a PIL image with Tesseract."""
    pytesseract = _require("pytesseract", "pytesseract")
    try:
        text = pytesseract.image_to_string(image, lang=tess_lang)
    except pytesseract.TesseractError:
        # Language pack missing -> fall back to English so we still work.
        text = pytesseract.image_to_string(image, lang="eng")
    except pytesseract.pytesseract.TesseractNotFoundError as exc:
        raise MissingDependency(
            "The Tesseract OCR engine is not installed or not on PATH.\n"
            "  macOS:    brew install tesseract\n"
            "  Ubuntu:   sudo apt install tesseract-ocr\n"
            "  Windows:  https://github.com/UB-Mannheim/tesseract/wiki"
        ) from exc
    # Collapse whitespace/newlines into clean lines.
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Translation
# --------------------------------------------------------------------------- #
class Translator:
    """Thin cached wrapper around deep-translator's GoogleTranslator."""

    def __init__(self, source: str, target: str):
        self.source = source
        self.target = target

    @staticmethod
    @lru_cache(maxsize=512)
    def _translate(text: str, source: str, target: str) -> str:
        deep = _require("deep_translator", "deep-translator")
        from deep_translator import GoogleTranslator

        return GoogleTranslator(source=source, target=target).translate(text)

    def translate(self, text: str) -> str:
        if not text.strip():
            return ""
        try:
            return self._translate(text, self.source, self.target)
        except Exception as exc:  # network / API hiccup - keep the app alive
            return f"[translation error: {exc}]"


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


# --------------------------------------------------------------------------- #
# Tkinter UI
# --------------------------------------------------------------------------- #
def run_gui(initial: Settings):
    try:
        import tkinter as tk
        from tkinter import ttk
    except ImportError as exc:
        raise MissingDependency(
            "Tkinter is not available. It normally ships with Python, but "
            "some systems need it separately:\n"
            "  Ubuntu/Debian:  sudo apt install python3-tk\n"
            "  Fedora:         sudo dnf install python3-tkinter\n"
            "  macOS (brew):   brew install python-tk"
        ) from exc

    settings = initial
    result_queue: "queue.Queue[tuple[str, str]]" = queue.Queue()
    worker_stop = threading.Event()
    worker_thread: Optional[threading.Thread] = None

    root = tk.Tk()
    root.title("Live Screen Translator")
    root.geometry("380x260")
    root.resizable(False, False)

    # ---- Region selection overlay ------------------------------------- #
    def select_region():
        """Fullscreen translucent overlay; drag a rectangle to pick a region."""
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
            text="Drag to select a region  ·  Esc to cancel",
            fill="white", font=("Helvetica", 18),
        )

        state = {"x0": 0, "y0": 0, "rect": None}

        def on_press(event):
            state["x0"], state["y0"] = event.x_root, event.y_root
            state["rect"] = canvas.create_rectangle(
                event.x, event.y, event.x, event.y,
                outline="#00e5ff", width=2,
            )

        def on_drag(event):
            if state["rect"] is not None:
                x0 = state["x0"] - overlay.winfo_rootx()
                y0 = state["y0"] - overlay.winfo_rooty()
                canvas.coords(state["rect"], x0, y0, event.x, event.y)

        def on_release(event):
            x0, y0 = state["x0"], state["y0"]
            x1, y1 = event.x_root, event.y_root
            region = Region(
                x=min(x0, x1), y=min(y0, y1),
                w=abs(x1 - x0), h=abs(y1 - y0),
            )
            overlay.destroy()
            if region.valid():
                settings.update(region=region)
                region_var.set(f"Region: {region.w}×{region.h} @ "
                              f"({region.x},{region.y})")
                start_btn.config(state="normal")

        def cancel(_=None):
            overlay.destroy()

        canvas.bind("<ButtonPress-1>", on_press)
        canvas.bind("<B1-Motion>", on_drag)
        canvas.bind("<ButtonRelease-1>", on_release)
        overlay.bind("<Escape>", cancel)
        overlay.focus_force()

    # ---- Translation overlay window ----------------------------------- #
    overlay_win = {"win": None, "label": None}

    def ensure_overlay():
        if overlay_win["win"] is not None:
            return
        region = settings.snapshot().region
        if region is None:
            return
        win = tk.Toplevel(root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        try:
            win.attributes("-alpha", 0.9)
        except tk.TclError:
            pass
        win.configure(bg="#101418")

        # Place the overlay *outside* the captured region so it never OCRs
        # its own text. Prefer directly below; fall back to above.
        screen_h = root.winfo_screenheight()
        width = max(region.w, 260)
        pad = 6
        below_y = region.y + region.h + pad
        overlay_h = 120
        if below_y + overlay_h <= screen_h:
            pos_x, pos_y = region.x, below_y
        else:
            pos_x, pos_y = region.x, max(0, region.y - overlay_h - pad)
        win.geometry(f"{width}x{overlay_h}+{pos_x}+{pos_y}")

        label = tk.Label(
            win, text="Waiting for text…", justify="left", anchor="nw",
            wraplength=width - 16, bg="#101418", fg="#e8f0f2",
            font=("Helvetica", 13), padx=8, pady=8,
        )
        label.pack(fill="both", expand=True)

        # Let the user drag the overlay around.
        drag = {"x": 0, "y": 0}

        def start_move(e):
            drag["x"], drag["y"] = e.x, e.y

        def do_move(e):
            win.geometry(f"+{win.winfo_x() + e.x - drag['x']}"
                        f"+{win.winfo_y() + e.y - drag['y']}")

        label.bind("<ButtonPress-1>", start_move)
        label.bind("<B1-Motion>", do_move)

        overlay_win["win"] = win
        overlay_win["label"] = label

    def destroy_overlay():
        if overlay_win["win"] is not None:
            overlay_win["win"].destroy()
            overlay_win["win"] = None
            overlay_win["label"] = None

    # ---- Worker thread ------------------------------------------------- #
    def worker():
        translator = None
        last_ocr = None
        cfg = settings.snapshot()
        source_code = LANGUAGES[cfg.source_name]["tr"]
        target_code = LANGUAGES[cfg.target_name]["tr"]
        translator = Translator(source_code, target_code)

        while not worker_stop.is_set():
            cfg = settings.snapshot()
            if cfg.region is None:
                time.sleep(0.2)
                continue

            # Rebuild translator if languages changed.
            src = LANGUAGES[cfg.source_name]["tr"]
            tgt = LANGUAGES[cfg.target_name]["tr"]
            if (src, tgt) != (translator.source, translator.target):
                translator = Translator(src, tgt)
                last_ocr = None

            try:
                image = grab_region(cfg.region)
                text = ocr_image(image, LANGUAGES[cfg.source_name]["ocr"])
            except MissingDependency as exc:
                result_queue.put(("[setup]", str(exc)))
                worker_stop.set()
                break
            except Exception as exc:  # keep looping on transient errors
                result_queue.put(("[error]", f"Capture/OCR failed: {exc}"))
                time.sleep(cfg.interval)
                continue

            if text and text != last_ocr:
                last_ocr = text
                translated = translator.translate(text)
                result_queue.put((text, translated))

            worker_stop.wait(cfg.interval)

    # ---- Queue polling (UI thread) ------------------------------------ #
    def poll_queue():
        try:
            while True:
                original, translated = result_queue.get_nowait()
                ensure_overlay()
                if overlay_win["label"] is not None:
                    overlay_win["label"].config(text=translated or "…")
                status_var.set(f"Last update: {time.strftime('%H:%M:%S')}")
        except queue.Empty:
            pass
        root.after(120, poll_queue)

    # ---- Start / stop -------------------------------------------------- #
    def start():
        nonlocal worker_thread
        if settings.snapshot().region is None:
            status_var.set("Select a region first.")
            return
        settings.update(
            source_name=source_var.get(),
            target_name=target_var.get(),
            interval=float(interval_var.get()),
        )
        worker_stop.clear()
        ensure_overlay()
        worker_thread = threading.Thread(target=worker, daemon=True)
        worker_thread.start()
        start_btn.config(state="disabled")
        stop_btn.config(state="normal")
        status_var.set("Running…")

    def stop():
        worker_stop.set()
        destroy_overlay()
        start_btn.config(state="normal")
        stop_btn.config(state="disabled")
        status_var.set("Stopped.")

    def on_close():
        worker_stop.set()
        root.after(150, root.destroy)

    # ---- Layout -------------------------------------------------------- #
    pad = {"padx": 8, "pady": 4}
    frm = ttk.Frame(root, padding=10)
    frm.pack(fill="both", expand=True)

    ttk.Label(frm, text="Translate from:").grid(row=0, column=0, sticky="w", **pad)
    source_var = tk.StringVar(value=settings.source_name)
    ttk.Combobox(frm, textvariable=source_var, values=list(LANGUAGES),
                state="readonly", width=22).grid(row=0, column=1, **pad)

    ttk.Label(frm, text="Translate to:").grid(row=1, column=0, sticky="w", **pad)
    target_names = [n for n in LANGUAGES if n != "Auto-detect"]
    target_var = tk.StringVar(value=settings.target_name)
    ttk.Combobox(frm, textvariable=target_var, values=target_names,
                state="readonly", width=22).grid(row=1, column=1, **pad)

    ttk.Label(frm, text="Refresh (sec):").grid(row=2, column=0, sticky="w", **pad)
    interval_var = tk.StringVar(value=str(settings.interval))
    ttk.Spinbox(frm, from_=0.3, to=10.0, increment=0.1, textvariable=interval_var,
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
    ttk.Label(frm, textvariable=status_var, foreground="#555").grid(
        row=5, column=0, columnspan=2, sticky="w", **pad)

    if settings.region is not None:
        region_var.set(f"Region: {settings.region.w}×{settings.region.h}")
        start_btn.config(state="normal")

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.after(120, poll_queue)
    root.mainloop()


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Live screen-region translator: drag-select part of your "
                   "screen and see a real-time translation overlay.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--from", dest="source", default=DEFAULT_SOURCE,
                       choices=list(LANGUAGES),
                       help="Source language (of the on-screen text).")
    parser.add_argument("--to", dest="target", default=DEFAULT_TARGET,
                       choices=[n for n in LANGUAGES if n != "Auto-detect"],
                       help="Target language (what to translate into).")
    parser.add_argument("--interval", type=float, default=DEFAULT_INTERVAL,
                       help="Seconds between capture/translate passes.")
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
