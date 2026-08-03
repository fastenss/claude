# PyInstaller spec for the Live Screen Translator.
#
# Build (on Windows):
#     pip install -r requirements.txt pyinstaller
#     pyinstaller --noconfirm live_translate.spec
#
# Output: dist\LiveScreenTranslator\LiveScreenTranslator.exe  (a folder build —
# recommended over one-file because EasyOCR/PyTorch are large and one-file
# unpacks them to a temp dir on every launch).

from PyInstaller.utils.hooks import collect_all

# EasyOCR + PyTorch + OpenCV ship data files and dynamically-imported modules
# that PyInstaller can't discover on its own, so pull them in wholesale.
_datas, _binaries, _hidden = [], [], []
for _pkg in (
    "easyocr",       # OCR models glue + character dictionaries
    "torch",         # tensor runtime (DLLs)
    "torchvision",   # used by some easyocr paths
    "cv2",           # opencv
    "skimage",       # scikit-image (easyocr dependency)
    "scipy",
    "dxcam",         # capture backend (Windows)
):
    try:
        d, b, h = collect_all(_pkg)
        _datas += d
        _binaries += b
        _hidden += h
    except Exception:
        pass  # package not installed on this platform -> skip

_hidden += [
    "deep_translator",
    "bidi",
    "pyclipper",
    "shapely",
    "yaml",
    "PIL",
    "PIL._tkinter_finder",
]


a = Analysis(
    ["live_translate.py"],
    pathex=[],
    binaries=_binaries,
    datas=_datas,
    hiddenimports=_hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=["matplotlib", "pandas", "notebook", "IPython"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="LiveScreenTranslator",
    console=False,          # GUI app: no console window
    disable_windowed_traceback=False,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="LiveScreenTranslator",
)
