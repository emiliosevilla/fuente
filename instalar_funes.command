#!/bin/bash
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"
export PYTHONPATH="$DIR:$PYTHONPATH"
export TK_SILENCE_DEPRECATION=1

confirm() {
    local prompt="$1"
    local reply
    read -r -p "$prompt [s/N]: " reply
    [[ "$reply" =~ ^[sS]$ ]]
}

echo "======================================================="
echo "             INSTALACIÓN DE FUNES (macOS)"
echo "======================================================="
echo ""

if ! command -v python3 &> /dev/null; then
    echo "[!] Python 3 no está instalado en este Mac."
    if command -v brew &> /dev/null; then
        if confirm "¿Instalar Python 3 vía Homebrew?"; then
            brew install python
        else
            echo "Instalación cancelada. Abriendo página de descarga..."
            open "https://www.python.org/downloads/mac-osx/"
            exit 1
        fi
    else
        echo "Abriendo la página oficial de descarga de Python (https://www.python.org/downloads/mac-osx/)..."
        open "https://www.python.org/downloads/mac-osx/"
    fi
    read -p "Tras finalizar la instalación de Python, vuelve a ejecutar este archivo. Presiona Enter para salir..."
    exit 1
fi

if [ ! -d "venv" ]; then
    echo "Creando entorno virtual Python..."
    python3 -m venv venv
else
    echo "[+] Entorno virtual existente detectado — se reutilizará."
fi

source venv/bin/activate
export PYTHONPATH="$DIR:$PYTHONPATH"
export TK_SILENCE_DEPRECATION=1

pip install --upgrade pip
if confirm "¿Instalar extras completos (.[all]) para audio/OCR/ofimática?"; then
    if [ -f "pyproject.toml" ] || [ -f "setup.py" ]; then
        pip install -e ".[all]"
    fi
else
    if [ -f "pyproject.toml" ] || [ -f "setup.py" ]; then
        pip install -e .
    fi
fi
if [ -f "requirements.txt" ]; then
    pip install -r requirements.txt
fi

echo ""
echo "Creando acceso directo ejecutable Funes.command en el Escritorio..."
if [ -f "./Funes_macOS" ]; then
    chmod +x ./Funes_macOS
fi
./venv/bin/python3 create_shortcuts.py

echo ""
echo "Comprobando instalación de Obsidian..."
if [ ! -d "/Applications/Obsidian.app" ] && ! command -v obsidian &> /dev/null; then
    echo "[!] Obsidian no está instalado en este Mac."
    if command -v brew &> /dev/null; then
        if confirm "¿Instalar Obsidian vía Homebrew?"; then
            brew install --cask obsidian
        else
            echo "Abriendo página de descarga de Obsidian..."
            open "https://obsidian.md/download"
        fi
    else
        echo "Abriendo la página oficial de descarga de Obsidian (https://obsidian.md/download)..."
        open "https://obsidian.md/download"
    fi
else
    echo "[+] Obsidian ya detectado — no se reinstala."
fi

echo ""
echo "Comprobando servicio de IA Local (Ollama)..."
if ! command -v ollama &> /dev/null && [ ! -d "/Applications/Ollama.app" ]; then
    echo "[!] Ollama no está instalado en este Mac."
    if command -v brew &> /dev/null; then
        if confirm "¿Instalar Ollama vía Homebrew?"; then
            brew install --cask ollama
        else
            echo "Abriendo página de descarga de Ollama..."
            open "https://ollama.com/download"
        fi
    else
        echo "Abriendo la página oficial de descarga de Ollama (https://ollama.com/download)..."
        open "https://ollama.com/download"
    fi
else
    echo "[+] Ollama ya detectado — no se reinstala."
fi

echo "Verificando que el servicio Ollama responda..."
if ! ./venv/bin/python3 -c "from funes.installer_contract import is_ollama_api_ready, start_ollama_service; import sys; sys.exit(0 if (is_ollama_api_ready() or start_ollama_service()) else 1)"; then
    echo "[!] Ollama no responde en http://localhost:11434. Inícialo manualmente con \`ollama serve\` o abre la app Ollama."
fi

echo ""
echo "Iniciando Asistente Gráfico de Instalación de Funes..."
if [ -f "./venv/bin/python3" ]; then
    ./venv/bin/python3 -m funes.installer_gui
else
    python3 -m funes.installer_gui
fi
