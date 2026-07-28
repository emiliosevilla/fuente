@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

TITLE Funes — Auto Instalador y Ejecutable
echo =======================================================
echo          FUNES KNOWLEDGE BASE ETL FOR OBSIDIAN
echo =======================================================
echo.

echo 1. Comprobando instalacion de Python 3...
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
pip install -e .

echo.
echo 3. Creando acceso directo Funes.lnk en el Escritorio...
python create_shortcuts.py

echo.
echo 4. Comprobando instalacion de Obsidian...
if not exist "%LocalAppData%\Programs\obsidian\Obsidian.exe" (
    if not exist "%ProgramFiles%\Obsidian\Obsidian.exe" (
        where obsidian >nul 2>&1
        if %errorlevel% neq 0 (
            echo [!] Obsidian no esta instalado en este equipo.
            where winget >nul 2>&1
            if %errorlevel% equ 0 (
                echo Instalando Obsidian automaticamente via Winget...
                winget install --id Obsidian.Obsidian -e --accept-package-agreements --accept-source-agreements
            ) else (
                echo Abriendo la página oficial de descarga de Obsidian (https://obsidian.md/download)...
                start https://obsidian.md/download
            )
        ) else (
            echo [+] Obsidian detectado en el sistema.
        )
    ) else (
        echo [+] Obsidian detectado en Program Files.
    )
) else (
    echo [+] Obsidian detectado en AppData.
)

echo.
echo 5. Comprobando servicio de IA Local (Ollama)...
curl -s http://localhost:11434/api/tags >nul 2>&1
if %errorlevel% neq 0 (
    where ollama >nul 2>&1
    if %errorlevel% equ 0 (
        echo Iniciando servicio local Ollama en segundo plano...
        start /b ollama serve >nul 2>&1
        timeout /t 3 >nul
    ) else (
        echo [!] Nota: Ollama no responde en http://localhost:11434
        echo     Para inferencia con IA local, descárgalo e inícialo desde https://ollama.com/
    )
)

echo.
echo 6. Iniciando Funes Knowledge Base...
set /p VAULT_PATH="Introduce la ruta a tu Vault de Obsidian (presiona Enter para usar ./Funes): "
if not "%VAULT_PATH%"=="" (
    set VAULT_PATH=%VAULT_PATH:"=%
    python funes\main.py --vault "!VAULT_PATH!"
) else (
    python funes\main.py --vault ".\Funes"
fi

pause
