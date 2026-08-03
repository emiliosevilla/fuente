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
    'funes.core.app_checker',
    'funes.core.anythingllm_config',
    'funes.core.folder_sync',
    'funes.control_console',
    'funes.installer_gui',
    'funes.extractors.base',
    'funes.extractors.office_pdf',
    'funes.extractors.tex_tm',
    'funes.extractors.audio',
    'funes.extractors.ocr_image',
    'funes.extractors.extended_formats',
    'funes.extractors.registry',
    'funes.ram_governor.governor',
    'funes.rag.chroma_store',
    'funes.rag.semantic_chunker',
    'funes.rag.hybrid_search',
    'funes.graph_engine.prompts',
    'funes.graph_engine.atomic_generator',
    'funes.graph_engine.linker',
    'funes.graph_engine.optimized_loop',
    'funes.watcher.watcher',
    'watchdog',
    'watchdog.observers',
    'psutil',
    'requests',
    'urllib.request',
    'tkinter',
    'tkinter.filedialog',
    'json',
    'pyyaml',
    'yaml',
    'sqlite3',

]

for pkg in ['psutil', 'watchdog', 'requests', 'pydantic', 'pdfplumber', 'docx', 'pptx', 'openpyxl', 'extract_msg', 'PIL', 'pytesseract', 'markitdown']:
    try:
        hidden_imports += collect_submodules(pkg)
    except Exception:
        pass

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
    name='Funes_macOS' if sys.platform == 'darwin' else 'Funes_windows',
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
