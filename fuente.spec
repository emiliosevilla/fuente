# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules

block_cipher = None
icon = Path("assets/fuente_icon.ico")
runtime_source = Path("build/runtime-source.zip")
if not icon.is_file():
    raise FileNotFoundError(f"PyInstaller icon missing: {icon.resolve()}")
if not runtime_source.is_file():
    raise FileNotFoundError("Run build_installer.py before building fuente.spec.")

a = Analysis(
    ["fuente/bootstrap.py"],
    pathex=["."],
    binaries=[],
    datas=[
        ("assets", "assets"),
        ("fuente/ui/static", "fuente/ui/static"),
        ("consola_preview.html", "."),
        ("build/pip-source.zip", "."),
        ("build/runtime-source.zip", "."),
    ],
    hiddenimports=[
        "webview.platforms.cocoa",
        "optparse",
        "colorsys",
        "tkinter.ttk",
        "tkinter.messagebox",
        "tkinter.filedialog",
        *collect_submodules("pip"),
    ],
    excludes=[
        "av",
        "chromadb",
        "cv2",
        "docling",
        "faster_whisper",
        "markitdown",
        "minirag",
        "numpy",
        "onnxruntime",
        "pandas",
        "pdfminer",
        "PIL",
        "sentence_transformers",
        "setuptools",
        "torch",
        "torchvision",
        "transformers",
        "webview.platforms.cef",
        "webview.platforms.edgechromium",
        "webview.platforms.gtk",
        "webview.platforms.mshtml",
        "webview.platforms.qt",
        "webview.platforms.win32",
        "webview.platforms.winforms",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Fuente",
    console=False,
    icon=str(icon),
)
coll = COLLECT(exe, a.binaries, a.zipfiles, a.datas, name="Fuente")
app = BUNDLE(
    coll,
    name="Fuente.app",
    icon=str(icon),
    bundle_identifier="com.emiliosevilla.fuente",
)
