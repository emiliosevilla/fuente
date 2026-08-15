# -*- mode: python ; coding: utf-8 -*-
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# Icon asset verified present at assets/fuente_icon.ico (Task 7.1).
_ICON_PATH = Path('assets/fuente_icon.ico')
if not _ICON_PATH.is_file():
    raise FileNotFoundError(f"PyInstaller icon missing: {_ICON_PATH.resolve()}")

datas = [('fuente', 'fuente'), ('assets', 'assets')]
hidden_imports = [
    'fuente',
    'fuente.config',
    'fuente.core.vault',
    'fuente.core.icon_generator',
    'fuente.core.app_checker',
    'fuente.core.anythingllm_config',
    'fuente.core.folder_sync',
    'fuente.control_console',
    'fuente.installer_gui',
    'fuente.extractors.base',
    'fuente.extractors.office_pdf',
    'fuente.extractors.tex_tm',
    'fuente.extractors.audio',
    'fuente.extractors.ocr_image',
    'fuente.extractors.extended_formats',
    'fuente.extractors.registry',
    'fuente.ram_governor.governor',
    'fuente.rag.chroma_store',
    'fuente.rag.semantic_chunker',
    'fuente.rag.hybrid_search',
    'fuente.graph_engine.prompts',
    'fuente.graph_engine.atomic_generator',
    'fuente.graph_engine.linker',
    'fuente.graph_engine.optimized_loop',
    'fuente.watcher.watcher',
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

for pkg in [
    'psutil', 'watchdog', 'requests', 'pydantic', 'pdfplumber', 'docx', 'pptx',
    'openpyxl', 'extract_msg', 'PIL', 'pytesseract', 'markitdown', 'docling',
    'faster_whisper', 'webview',
]:
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
    ['fuente/main.py'],
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
    name='Fuente_macOS' if sys.platform == 'darwin' else 'Fuente_windows',
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
    icon=str(_ICON_PATH),
)
