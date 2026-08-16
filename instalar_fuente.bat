@echo off
setlocal enabledelayedexpansion
set "ROOT_DIR=%~dp0"
if "%ROOT_DIR:~-1%"=="\" set "ROOT_DIR=%ROOT_DIR:~0,-1%"
cd /d "%ROOT_DIR%"
set "PYTHONPATH=%ROOT_DIR%;%PYTHONPATH%"

TITLE Fuente — Auto Instalador y Ejecutable
echo =======================================================
echo               INSTALACION DE FUENTE
echo =======================================================
echo.

echo 1. Comprobando instalacion de Python 3...
python --version >nul 2>&1
if !errorlevel! neq 0 (
    py --version >nul 2>&1
    if !errorlevel! neq 0 (
        echo [!] Python 3 no esta instalado en este equipo.
        where winget >nul 2>&1
        if !errorlevel! equ 0 (
            set /p INSTALL_PY="¿Instalar Python 3 via Winget? [s/N]: "
            if /I "!INSTALL_PY!"=="s" (
                winget install --id Python.Python.3.12 -e --accept-package-agreements --accept-source-agreements
                echo [!] Python 3 ha sido instalado. Por favor vuelve a ejecutar este instalador.
                pause
                exit /b 0
            ) else (
                echo Instalacion cancelada. Abriendo pagina de descarga...
                start https://www.python.org/downloads/
                pause
                exit /b 1
            )
        ) else (
            echo Abriendo la pagina oficial de descarga de Python https://www.python.org/downloads/ ...
            start https://www.python.org/downloads/
            pause
            exit /b 1
        )
    )
)

echo.
echo 2. Creando entorno virtual e instalando dependencias...
if not exist "venv" (
    python -m venv venv 2>nul || py -m venv venv
) else (
    echo [+] Entorno virtual existente detectado — se reutilizara.
)

call venv\Scripts\activate.bat
set "PYTHONPATH=%ROOT_DIR%;%PYTHONPATH%"

python -m pip install --upgrade pip
set /p FEATURE_SET="Instalar extras completos (.[all]) para audio/OCR/ofimatica? [s/N]: "
if /I "!FEATURE_SET!"=="s" (
    set "FUENTE_INSTALL_OCR=1"
    if exist pyproject.toml (
        pip install -e ".[all]"
    ) else if exist setup.py (
        pip install -e ".[all]"
    )
) else (
    set "FUENTE_INSTALL_OCR=0"
    if exist pyproject.toml (
        pip install -e .
    ) else if exist setup.py (
        pip install -e .
    )
)
if exist requirements.txt pip install -r requirements.txt

echo.
echo 3. Creando acceso directo Fuente.lnk en el Escritorio...
python create_shortcuts.py

echo.
echo 4. Comprobando instalacion de Obsidian...
set "OBSIDIAN_FOUND=0"
if exist "%LocalAppData%\Programs\obsidian\Obsidian.exe" set "OBSIDIAN_FOUND=1"
if exist "%ProgramFiles%\Obsidian\Obsidian.exe" set "OBSIDIAN_FOUND=1"
where obsidian >nul 2>&1
if !errorlevel! equ 0 set "OBSIDIAN_FOUND=1"

if "!OBSIDIAN_FOUND!"=="0" (
    echo [!] Obsidian no esta instalado en este equipo.
    where winget >nul 2>&1
    if !errorlevel! equ 0 (
        set /p INSTALL_OBS="¿Instalar Obsidian via Winget? [s/N]: "
        if /I "!INSTALL_OBS!"=="s" (
            winget install --id Obsidian.Obsidian -e --accept-package-agreements --accept-source-agreements
        ) else (
            echo Abriendo pagina de descarga de Obsidian...
            start https://obsidian.md/download
        )
    ) else (
        echo Abriendo la pagina oficial de descarga de Obsidian https://obsidian.md/download ...
        start https://obsidian.md/download
    )
) else (
    echo [+] Obsidian ya detectado — no se reinstala.
)

echo.
echo 5. Comprobando servicio de IA Local (Ollama)...
set "OLLAMA_FOUND=0"
where ollama >nul 2>&1
if !errorlevel! equ 0 set "OLLAMA_FOUND=1"

if "!OLLAMA_FOUND!"=="0" (
    echo [!] Ollama no esta instalado en este equipo.
    where winget >nul 2>&1
    if !errorlevel! equ 0 (
        set /p INSTALL_OLL="¿Instalar Ollama via Winget? [s/N]: "
        if /I "!INSTALL_OLL!"=="s" (
            winget install --id Ollama.Ollama -e --accept-package-agreements --accept-source-agreements
        ) else (
            echo Abriendo pagina de descarga de Ollama...
            start https://ollama.com/download
        )
    ) else (
        echo Abriendo la pagina oficial de descarga de Ollama https://ollama.com/download ...
        start https://ollama.com/download
    )
) else (
    echo [+] Ollama ya detectado — no se reinstala.
)

echo Verificando que el servicio Ollama responda...
python -c "from fuente.installer_contract import is_ollama_api_ready, start_ollama_service; import sys; sys.exit(0 if (is_ollama_api_ready() or start_ollama_service()) else 1)"
if !errorlevel! neq 0 (
    echo [!] Ollama no responde en http://localhost:11434. Inicialo manualmente con `ollama serve`.
)

echo.
echo 6. Iniciando Asistente Grafico de Instalacion de Fuente...
python -m fuente.installer_gui

pause
