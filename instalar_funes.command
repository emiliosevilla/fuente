#!/bin/bash
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

echo "======================================================="
echo "       FUNES KNOWLEDGE BASE ETL FOR OBSIDIAN (macOS)"
echo "======================================================="
echo ""

if ! command -v python3 &> /dev/null; then
    echo "[!] Python 3 no esta instalado. Por favor instalalo desde https://www.python.org/"
    read -p "Presiona Enter para salir..."
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
if ! curl -s http://localhost:11434/api/tags > /dev/null; then
    if command -v ollama &> /dev/null; then
        echo "Iniciando Ollama serve en segundo plano..."
        ollama serve > /dev/null 2>&1 &
        sleep 3
    else
        echo "[!] Nota: Ollama no esta instalado o respondiendo en http://localhost:11434"
        echo "    Para inferencia con IA local, descargalo desde https://ollama.com/"
    fi
fi

echo ""
echo "Iniciando Funes..."
read -p "Arrastra tu carpeta Vault de Obsidian aqui (o presiona Enter para usar ./Funes): " VAULT_INPUT

VAULT_INPUT=$(echo "$VAULT_INPUT" | sed "s/^'//;s/'$//;s/^\"//;s/\"$//")

if [ -n "$VAULT_INPUT" ]; then
    python3 funes/main.py --vault "$VAULT_INPUT"
else
    python3 funes/main.py --vault "./Funes"
fi
