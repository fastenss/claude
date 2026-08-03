# Live Screen Translator

Drag-select any part of your monitor and get a **real-time translation painted
directly over the original text**. Great for translating games, videos, PDFs,
foreign-language UIs, or anything else on screen that you can't copy-paste.

```
 ┌─────────────────┐            ┌─────────────────┐
 │  こんにちは世界  │  ───────►  │  Hello, world   │   ← translation is drawn
 │  (selected      │  capture   │  (drawn ON TOP  │     on top of the source,
 │   screen area)  │  OCR       │   of the text)  │     covering it in place
 └─────────────────┘  translate └─────────────────┘
```

## How it works

```
region ─► dxcam capture ─► change check (~2s) ─► EasyOCR ─► Google Translate ─► overlay
```

1. You drag a rectangle over the text you want translated.
2. Every ~2 seconds the app captures just that region and compares it to the
   previous frame. **OCR/translation only run when the pixels actually change**,
   so nothing is wasted while the screen is static.
3. When it changes, **EasyOCR** finds each text box and its position.
4. Each box is translated (results are cached), and the translation is painted
   over the original in a frameless overlay — with a background colour sampled
   from the region so it blends in and **completely covers the source text**.

### No-flicker overlay (Windows)

On Windows the app captures with **dxcam** (DirectX Desktop Duplication) and
marks the translation overlay with **`WDA_EXCLUDEFROMCAPTURE`**
(`SetWindowDisplayAffinity`). That flag keeps the overlay fully visible on your
screen but makes it **invisible to the capture pipeline** — so dxcam only ever
sees the original text underneath, and the overlay can stay up permanently. No
hide/show flicker.

On other platforms (or if the flag can't be set, e.g. older Windows) the app
falls back to **mss** capture and briefly hides the overlay for each frame
instead. The status bar shows which mode is active.

## Get it

### Option A — download the Windows .exe (no Python needed)

Grab `LiveScreenTranslator-windows.zip` from the repo's **Actions → Build
Windows EXE** run (or from a release), unzip it, and run
`LiveScreenTranslator.exe`. The dxcam no-flicker path only exists on Windows,
so this is the recommended way to use it there.

To build the .exe yourself on a Windows machine:

```bat
build.bat
```

…which produces `dist\LiveScreenTranslator\LiveScreenTranslator.exe`. (See
`live_translate.spec` for the PyInstaller configuration.)

### Option B — run from source

```bash
pip install -r requirements.txt
python live_translate.py
```

That pulls in **EasyOCR** (and its PyTorch / OpenCV dependencies) plus a capture
backend (**dxcam** on Windows, **mss** elsewhere). No separate OCR engine or API
key is required.

- **First run downloads the EasyOCR model** for your source language (~tens of
  MB), so the first translation after picking a language takes a little longer.
- **GPU is optional** — the app runs EasyOCR on CPU by default.
- Tkinter ships with Python; on some Linux distros install it separately
  (`sudo apt install python3-tk`).

## Usage

```bash
python live_translate.py
```

1. Click **Select region** and drag a box over the text you want translated.
2. Choose **Translate from** (or leave *Auto-detect*) and **Translate to**.
3. Click **Start**. The translation is drawn over your selection and refreshes
   whenever the underlying text changes.
4. Click **Stop** to remove the overlay.

### Command-line options

```bash
# Preset the languages
python live_translate.py --from Japanese --to English

# Check for changes more often
python live_translate.py --interval 1.0

# Skip the picker entirely with an explicit region (x,y,width,height)
python live_translate.py --region 100,100,600,200 --from Spanish --to English
```

Run `python live_translate.py --help` for the full list.

## Languages

EasyOCR can **read**: English, Spanish, French, German, Italian, Portuguese,
Dutch, Russian, Japanese, Korean, Chinese (Simplified/Traditional), Arabic,
Hindi, Turkish, Polish, Vietnamese, Thai, Ukrainian, and Indonesian.

You can **translate into** any of those plus Greek and Hebrew. *Auto-detect*
lets Google Translate figure out the source language (OCR falls back to English
in that mode, so pick the explicit source language for non-Latin scripts).

See the `LANGUAGES` table in `live_translate.py` to add more.

## Notes & tips

- **Translation uses Google Translate** via `deep-translator` — needs an
  internet connection but **no API key**.
- Bigger, higher-contrast text OCRs far better. If results are poor, select a
  tighter region around just the text.
- The overlay covers the whole selected region opaquely (that's how it fully
  hides the original); keep your selection close to the text.
- Raise `--interval` if you hit Google Translate rate limits; lower it for
  snappier updates.
- On multi-monitor setups the picker covers the primary display; `mss` captures
  whatever coordinates the region resolves to.
