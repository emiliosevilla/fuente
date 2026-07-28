# -*- mode: python ; coding: utf-8 -*-
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

datas = [('funes', 'funes'), ('assets', 'assets')]
hidden_imports = [
    'funes',
    'funes.config',
    'funes.core.vault',
    'funes.core.icon_generator',
    'funes.extractors.base',
    'funes.extractors.office_pdf',
    'funes.extractors.tex_tm',
    'funes.extractors.audio',
    'funes.extractors.ocr_image',
    'funes.extractors.registry',
    'funes.ram_governor.governor',
    'funes.rag.chroma_store',
    'funes.rag.semantic_chunker',
    'funes.graph_engine.prompts',
    'funes.graph_engine.atomic_generator',
    'funes.graph_engine.linker',
    'funes.graph_engine.karpathy_loop',
    'funes.watcher.watcher',
    'watchdog',
    'watchdog.observers',
    'psutil',
    'requests',
    'urllib.request',
    'tkinter',
    'tkinter.filedialog',
    'json',
    'yaml',
    'sqlite3',
]

try:
    datas += collect_data_files('chromadb')
    hidden_imports += collect_submodules('chromadb')
except Exception:
    pass

try:
    datas += collect_data_files('pdfplumber')
except Exception:
    pass

a = Analysis(
    ['funes/main.py'],
    pathex=['.'],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='Funes',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/funes_icon.ico',
)
