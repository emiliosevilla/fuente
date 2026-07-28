@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

TITLE Funes Knowledge Base — Auto Instalador y Ejecutable
echo =======================================================
echo          FUNES KNOWLEDGE BASE ETL FOR OBSIDIAN
echo =======================================================
echo.

echo 1. Comprobando instalacion de Python...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    py --version >nul 2>&1
    if %errorlevel% neq 0 (
        echo [!] Python 3 no se encuentra instalado en este equipo.
        echo Por favor instala Python 3 desde https://www.python.org/
        pause
        exit /b 1
    )
)

echo 2. Creando entorno virtual e instalando dependencias...
if not exist "venv" (
    python -m venv venv 2>nul || py -m venv venv
)

call venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt

echo.
echo 3. Comprobando servicio de IA Local (Ollama)...
curl -s http://localhost:11434/api/tags >nul 2>&1
if %errorlevel% neq 0 (
    echo [!] Nota: Ollama no responde en http://localhost:11434
    echo     Para inferencia con IA local, puedes iniciar Ollama desde https://ollama.com/
)

echo.
echo 4. Iniciando Funes Knowledge Base...
set /p VAULT_PATH="Introduce la ruta a tu Vault de Obsidian (o presiona Enter para usar ventana de seleccion): "
if not "%VAULT_PATH%"=="" (
    set VAULT_PATH=%VAULT_PATH:"=%
    python funes\main.py --vault "!VAULT_PATH!"
) else (
    python funes\main.py
)

pause
