#!/bin/bash
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"
export PYTHONPATH="$DIR:$PYTHONPATH"

echo "======================================================="
echo "               HABLA CON FUNES (macOS)"
echo "======================================================="
echo ""

if ! command -v python3 &> /dev/null; then
    echo "[!] Python 3 no está instalado en este Mac."
    if command -v brew &> /dev/null; then
        echo "Instalando Python 3 automáticamente vía Homebrew..."
        brew install python
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
fi

source venv/bin/activate
export PYTHONPATH="$DIR:$PYTHONPATH"

pip install --upgrade pip
if [ -f "requirements.txt" ]; then
    pip install -r requirements.txt
fi
if [ -f "pyproject.toml" ] || [ -f "setup.py" ]; then
    pip install -e .
fi

echo ""
echo "Creando acceso directo ejecutable Funes.command en el Escritorio..."
./venv/bin/python3 create_shortcuts.py

echo ""
echo "Comprobando instalación de Obsidian..."
if [ ! -d "/Applications/Obsidian.app" ] && ! command -v obsidian &> /dev/null; then
    echo "[!] Obsidian no está instalado en este Mac."
    if command -v brew &> /dev/null; then
        echo "Instalando Obsidian automáticamente vía Homebrew..."
        brew install --cask obsidian
    else
        echo "Abriendo la página oficial de descarga de Obsidian (https://obsidian.md/download)..."
        open "https://obsidian.md/download"
    fi
else
    echo "[+] Obsidian detectado correctamente."
fi

echo ""
echo "Comprobando servicio de IA Local (Ollama)..."
if ! command -v ollama &> /dev/null && [ ! -d "/Applications/Ollama.app" ]; then
    echo "[!] Ollama no está instalado en este Mac."
    if command -v brew &> /dev/null; then
        echo "Instalando Ollama automáticamente vía Homebrew..."
        brew install --cask ollama
    else
        echo "Abriendo la página oficial de descarga de Ollama (https://ollama.com/download)..."
        open "https://ollama.com/download"
    fi
else
    echo "[+] Ollama detectado correctamente."
fi

if ! curl -s http://localhost:11434/api/tags > /dev/null; then
    echo "Iniciando servicio local Ollama en segundo plano..."
    if command -v ollama &> /dev/null; then
        ollama serve > /dev/null 2>&1 &
        sleep 3
    elif [ -d "/Applications/Ollama.app" ]; then
        open -a Ollama
        sleep 3
    fi
fi

echo ""
echo "Iniciando Asistente Gráfico de Instalación de Funes..."
if [ -f "./venv/bin/python3" ]; then
    ./venv/bin/python3 -m funes.installer_gui
elif [ -f "./Funes_macOS" ]; then
    ./Funes_macOS
else
    python3 -m funes.installer_gui
fi
