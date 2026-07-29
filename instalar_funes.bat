@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

TITLE Funes — Auto Instalador y Ejecutable
echo =======================================================
echo                  HABLA CON FUNES
echo =======================================================
echo.

echo 1. Comprobando instalacion de Python 3...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    py --version >nul 2>&1
    if %errorlevel% neq 0 (
        echo [!] Python 3 no esta instalado en este equipo.
        where winget >nul 2>&1
        if %errorlevel% equ 0 (
            echo Instalando Python 3 automáticamente vía Winget...
            winget install --id Python.Python.3.12 -e --accept-package-agreements --accept-source-agreements
            echo [!] Python 3 ha sido instalado. Por favor vuelve a ejecutar este instalador.
            pause
            exit /b 0
        ) else (
            echo Abriendo la página oficial de descarga de Python (https://www.python.org/downloads/)...
            start https://www.python.org/downloads/
            pause
            exit /b 1
        )
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
where ollama >nul 2>&1
if %errorlevel% neq 0 (
    echo [!] Ollama no esta instalado en este equipo.
    where winget >nul 2>&1
    if %errorlevel% equ 0 (
        echo Instalando Ollama automaticamente via Winget...
        winget install --id Ollama.Ollama -e --accept-package-agreements --accept-source-agreements
    ) else (
        echo Abriendo la página oficial de descarga de Ollama (https://ollama.com/download)...
        start https://ollama.com/download
    )
) else (
    echo [+] Ollama detectado en el sistema.
)

curl -s http://localhost:11434/api/tags >nul 2>&1
if %errorlevel% neq 0 (
    where ollama >nul 2>&1
    if %errorlevel% equ 0 (
        echo Iniciando servicio local Ollama en segundo plano...
        start /b ollama serve >nul 2>&1
        timeout /t 3 >nul
    )
)

echo.
echo 6. Iniciando Asistente Gráfico de Instalación de Funes...
python -m funes.installer_gui

pause

