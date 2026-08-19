#!/bin/bash
set -euo pipefail

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"
export PYTHONPATH="$DIR${PYTHONPATH:+:$PYTHONPATH}"
export TK_SILENCE_DEPRECATION=1

confirm() {
    local prompt="$1"
    local reply
    read -r -p "$prompt [s/N]: " reply
    [[ "$reply" =~ ^[sS]$ ]]
}

open_url() { open "$1" 2>/dev/null || true; }
fail() { echo "[!] $1" >&2; exit 1; }

python_is_supported() {
    "$1" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1
}

find_python() {
    local candidate
    for candidate in python3 python; do
        if command -v "$candidate" >/dev/null 2>&1 && python_is_supported "$(command -v "$candidate")"; then
            PYTHON_BIN="$(command -v "$candidate")"
            return 0
        fi
    done
    return 1
}

echo "======================================================="
echo "             INSTALACIÓN DE FUENTE (macOS)"
echo "======================================================="
echo ""

[[ "$(uname -s)" == "Darwin" ]] || fail "Este instalador sólo funciona en macOS."
[[ -w "$DIR" ]] || fail "No hay permisos de escritura en $DIR. Mueve Fuente a una carpeta editable o concede permisos y repite."

if ! find_python; then
    echo "[!] Se necesita Python 3.10 o superior."
    if command -v brew >/dev/null 2>&1 && confirm "¿Instalar Python 3 mediante Homebrew?"; then
        brew install python
    else
        echo "Abriendo la descarga oficial de Python..."
        open_url "https://www.python.org/downloads/macos/"
        fail "Instala Python 3.10 o superior y vuelve a ejecutar este instalador."
    fi
    find_python || fail "Python se instaló, pero no aparece disponible en PATH. Reinicia Terminal y repite."
fi

echo "[+] Python detectado: $PYTHON_BIN"
if [ ! -x "venv/bin/python" ]; then
    echo "Creando entorno virtual Python..."
    "$PYTHON_BIN" -m venv venv
else
    echo "[+] Entorno virtual existente detectado — se reutilizará."
fi

VENV_PY="$DIR/venv/bin/python"
[ -x "$VENV_PY" ] || fail "No se pudo crear o localizar el Python del entorno virtual."
export FUENTE_INSTALL_OCR=0

"$VENV_PY" -m pip install --upgrade pip
if confirm "¿Instalar extras completos (.[all]) para audio/OCR/ofimática?"; then
    export FUENTE_INSTALL_OCR=1
    "$VENV_PY" -m pip install -e ".[all]"
else
    "$VENV_PY" -m pip install -e .
fi
if [ -f "requirements.txt" ]; then
    "$VENV_PY" -m pip install -r requirements.txt
fi

echo ""
echo "Creando accesos directos de Fuente..."
[ -f "create_shortcuts.py" ] || fail "Falta create_shortcuts.py en la distribución."
"$VENV_PY" create_shortcuts.py

echo ""
echo "Comprobando instalación de Obsidian..."
if [ ! -d "/Applications/Obsidian.app" ] && ! command -v obsidian >/dev/null 2>&1; then
    echo "[!] Obsidian no está instalado en este Mac."
    if command -v brew >/dev/null 2>&1 && confirm "¿Instalar Obsidian mediante Homebrew?"; then
        brew install --cask obsidian
    else
        open_url "https://obsidian.md/download"
    fi
else
    echo "[+] Obsidian ya detectado — no se reinstala."
fi

echo ""
echo "Comprobando servicio local de IA (Ollama)..."
if ! command -v ollama >/dev/null 2>&1 && [ ! -d "/Applications/Ollama.app" ]; then
    echo "[!] Ollama no está instalado en este Mac."
    if command -v brew >/dev/null 2>&1 && confirm "¿Instalar Ollama mediante Homebrew?"; then
        brew install --cask ollama
    else
        open_url "https://ollama.com/download"
    fi
else
    echo "[+] Ollama ya detectado — no se reinstala."
fi

echo "Verificando que el servicio Ollama responda..."
if ! "$VENV_PY" -c "from fuente.installer_contract import is_ollama_api_ready, start_ollama_service; import sys; sys.exit(0 if (is_ollama_api_ready() or start_ollama_service()) else 1)"; then
    echo "[!] Ollama no responde en http://localhost:11434. Inícialo manualmente con 'ollama serve' o abre la app Ollama."
fi

echo ""
echo "Iniciando Asistente Gráfico de Instalación de Fuente..."
exec "$VENV_PY" -m fuente.installer_gui
