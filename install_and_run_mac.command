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

echo "Iniciando Funes..."
read -p "Introduce la ruta a tu Vault de Obsidian (o presiona Enter para usar ./ObsidianVault): " VAULT_INPUT

if [ -z "$VAULT_INPUT" ]; then
    VAULT_INPUT="./ObsidianVault"
fi

python3 funes/main.py --vault "$VAULT_INPUT"
