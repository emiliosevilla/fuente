#!/bin/bash
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

echo "======================================================="
echo "       FUNES KNOWLEDGE BASE ETL FOR OBSIDIAN (macOS)"
echo "======================================================="
echo ""

if ! command -v python3 &> /dev/null; then
    echo "[!] Python 3 no esta instalado en este Mac."
    if command -v brew &> /dev/null; then
        echo "Instalando Python 3 automaticamente via Homebrew..."
        brew install python
    else
        echo "Abriendo la pagina oficial de descarga de Python (https://www.python.org/downloads/mac-osx/)..."
        open "https://www.python.org/downloads/mac-osx/"
    fi
    read -p "Tras finalizar la instalacion de Python, vuelve a ejecutar este archivo. Presiona Enter para salir..."
    exit 1
fi


if [ ! -d "venv" ]; then
    echo "Creando entorno virtual Python..."
    python3 -m venv venv
fi

source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
pip install -e .

echo ""
echo "Creando acceso directo ejecutable Funes.command en el Escritorio..."
python3 create_shortcuts.py

echo ""
echo "Comprobando instalacion de Obsidian..."
if [ ! -d "/Applications/Obsidian.app" ] && ! command -v obsidian &> /dev/null; then
    echo "[!] Obsidian no esta instalado en este Mac."
    if command -v brew &> /dev/null; then
        echo "Instalando Obsidian automaticamente via Homebrew..."
        brew install --cask obsidian
    else
        echo "Abriendo la pagina oficial de descarga de Obsidian (https://obsidian.md/download)..."
        open "https://obsidian.md/download"
    fi
else
    echo "[+] Obsidian detectado correctamente."
fi

echo ""
echo "Comprobando servicio de IA Local (Ollama)..."
if ! command -v ollama &> /dev/null && [ ! -d "/Applications/Ollama.app" ]; then
    echo "[!] Ollama no esta instalado en este Mac."
    if command -v brew &> /dev/null; then
        echo "Instalando Ollama automaticamente via Homebrew..."
        brew install --cask ollama
    else
        echo "Abriendo la pagina oficial de descarga de Ollama (https://ollama.com/download)..."
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
echo "Comprobando RAM y descargando el modelo Qwen óptimo..."
python3 -m funes.ram_governor.governor

echo ""
echo "Iniciando Funes..."
read -p "Arrastra tu carpeta Vault de Obsidian aqui (o presiona Enter para usar ./Funes_Vault): " VAULT_INPUT

VAULT_INPUT=$(echo "$VAULT_INPUT" | sed "s/^'//;s/'$//;s/^\"//;s/\"$//")

if [ -n "$VAULT_INPUT" ]; then
    python3 funes/main.py --vault "$VAULT_INPUT"
else
    python3 funes/main.py --vault "./Funes_Vault"
fi

