# Live Screen Translator

Drag-select any part of your monitor and get a **real-time translation** in a
floating overlay. Great for translating games, videos, PDFs, foreign-language
UIs, or anything else on screen that you can't copy-paste.

```
 ┌─────────────────┐          ┌─────────────────┐
 │  こんにちは世界  │  ──────► │  Hello, world   │
 │  (selected      │  capture │  (live overlay  │
 │   screen area)  │  OCR     │   below it)     │
 └─────────────────┘  translate└─────────────────┘
```

## How it works

```
screen region ──► mss (capture) ──► Tesseract (OCR) ──► Google Translate ──► overlay
```

1. You drag a rectangle over the part of the screen you want to read.
2. Every ~1 second the app screenshots just that region.
3. Tesseract extracts the text; only *changed* text is re-translated (cached).
4. `deep-translator` translates it, and the result is shown in a frameless,
   always-on-top window placed just outside your selection.

## Install

**1. Python packages**

```bash
pip install -r requirements.txt
```

**2. The Tesseract OCR engine** (this is a separate native program, not a pip package):

| OS      | Command                                                            |
|---------|-------------------------------------------------------------------|
| macOS   | `brew install tesseract`                                          |
| Ubuntu  | `sudo apt install tesseract-ocr`                                  |
| Windows | Installer: <https://github.com/UB-Mannheim/tesseract/wiki>       |

To OCR non-English text you also need that language's data pack, e.g.
`brew install tesseract-lang` (macOS) or `sudo apt install tesseract-ocr-jpn`
(Ubuntu, Japanese). Without the pack the app falls back to English OCR.

## Usage

```bash
python live_translate.py
```

1. Click **Select region** and drag a box over the text you want translated.
2. Choose **Translate from** (or leave *Auto-detect*) and **Translate to**.
3. Click **Start**. A live overlay appears next to your selection.
4. Drag the overlay anywhere; click **Stop** to pause.

### Command-line options

```bash
# Preset the languages and skip auto-detect
python live_translate.py --from Japanese --to English

# Faster refresh
python live_translate.py --interval 0.6

# Skip the picker entirely with an explicit region (x,y,width,height)
python live_translate.py --region 100,100,600,200 --from Spanish --to English
```

Run `python live_translate.py --help` for the full list.

## Supported languages

English, Spanish, French, German, Italian, Portuguese, Dutch, Russian,
Japanese, Korean, Chinese (Simplified/Traditional), Arabic, Hindi, Turkish,
Polish, Vietnamese, Thai, Ukrainian, Greek, Hebrew, Indonesian — plus
**Auto-detect** for the source. (See `LANGUAGES` in `live_translate.py` to add
more.)

## Notes & tips

- **Translation uses Google Translate** via `deep-translator`, so it needs an
  internet connection but **no API key**.
- The overlay is intentionally placed **below/above** your selection so it
  never ends up screenshotting and re-translating its own text.
- Bigger, higher-contrast text OCRs far better than tiny or low-contrast text.
  If OCR is poor, select a tighter region around just the text.
- On multi-monitor setups the region picker covers the primary display; `mss`
  itself captures whichever coordinates the region resolves to.
- Increase `--interval` if you hit Google Translate rate limits; decrease it
  for snappier updates.
