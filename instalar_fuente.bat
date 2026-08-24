@echo off
setlocal EnableExtensions EnableDelayedExpansion
set "ROOT_DIR=%~dp0"
if "%ROOT_DIR:~-1%"=="\" set "ROOT_DIR=%ROOT_DIR:~0,-1%"
cd /d "%ROOT_DIR%"
set "PYTHONPATH=%ROOT_DIR%;%PYTHONPATH%"

TITLE Fuente - Instalador
echo =======================================================
echo               INSTALACION DE FUENTE
echo =======================================================
echo.

echo 1. Comprobando instalacion de Python 3.10 o superior...
set "PYTHON_CMD="
python -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1
if !errorlevel! equ 0 set "PYTHON_CMD=python"
if not defined PYTHON_CMD (
    py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1
    if !errorlevel! equ 0 set "PYTHON_CMD=py -3"
)

if not defined PYTHON_CMD (
    echo [!] Se necesita Python 3.10 o superior.
    where winget >nul 2>&1
    if !errorlevel! equ 0 (
        set /p INSTALL_PY="Instalar Python 3.12 mediante Winget? [s/N]: "
        if /I "!INSTALL_PY!"=="s" (
            winget install --id Python.Python.3.12 -e --accept-package-agreements --accept-source-agreements
            if !errorlevel! neq 0 goto :fail
            set "PYTHON_CMD=py -3"
        ) else (
            start https://www.python.org/downloads/windows/
            echo Instala Python 3.10 o superior y vuelve a ejecutar este instalador.
            pause
            exit /b 1
        )
    ) else (
        start https://www.python.org/downloads/windows/
        echo Instala Python 3.10 o superior y vuelve a ejecutar este instalador.
        pause
        exit /b 1
    )
)

echo [+] Python detectado: !PYTHON_CMD!
echo.
echo 2. Creando entorno virtual e instalando dependencias...
if not exist "venv\Scripts\python.exe" (
    !PYTHON_CMD! -m venv venv
    if !errorlevel! neq 0 goto :fail
) else (
    echo [+] Entorno virtual existente detectado - se reutilizara.
)

set "VENV_PY=%ROOT_DIR%\venv\Scripts\python.exe"
if not exist "%VENV_PY%" goto :fail
set "FUENTE_INSTALL_OCR=1"
"%VENV_PY%" -m pip install --upgrade pip
if !errorlevel! neq 0 goto :fail
echo [+] Instalando el conjunto completo de funciones locales (audio, OCR, ofimatica y RAG)...
"%VENV_PY%" -m pip install -e ".[all]"
if !errorlevel! neq 0 goto :fail
if exist requirements.txt "%VENV_PY%" -m pip install -r requirements.txt
if !errorlevel! neq 0 goto :fail

echo.
echo 3. Creando accesos directos de Fuente...
if not exist "create_shortcuts.py" goto :fail
"%VENV_PY%" create_shortcuts.py
if !errorlevel! neq 0 goto :fail

echo.
echo 4. Comprobando instalacion de Obsidian...
set "OBSIDIAN_FOUND=0"
if exist "%LocalAppData%\Programs\obsidian\Obsidian.exe" set "OBSIDIAN_FOUND=1"
if exist "%ProgramFiles%\Obsidian\Obsidian.exe" set "OBSIDIAN_FOUND=1"
where obsidian >nul 2>&1
if !errorlevel! equ 0 set "OBSIDIAN_FOUND=1"
if "!OBSIDIAN_FOUND!"=="0" (
    where winget >nul 2>&1
    if !errorlevel! equ 0 (
        set /p INSTALL_OBS="Instalar Obsidian mediante Winget? [s/N]: "
        if /I "!INSTALL_OBS!"=="s" winget install --id Obsidian.Obsidian -e --accept-package-agreements --accept-source-agreements
    ) else (
        start https://obsidian.md/download
    )
)

echo.
echo 5. Comprobando servicio local de IA (Ollama)...
where ollama >nul 2>&1
if !errorlevel! neq 0 (
    where winget >nul 2>&1
    if !errorlevel! equ 0 (
        set /p INSTALL_OLL="Instalar Ollama mediante Winget? [s/N]: "
        if /I "!INSTALL_OLL!"=="s" winget install --id Ollama.Ollama -e --accept-package-agreements --accept-source-agreements
    ) else (
        start https://ollama.com/download
    )
)

echo Verificando que el servicio Ollama responda...
"%VENV_PY%" -c "from fuente.installer_contract import is_ollama_api_ready, start_ollama_service; import sys; sys.exit(0 if (is_ollama_api_ready() or start_ollama_service()) else 1)"
if !errorlevel! neq 0 echo [!] Ollama no responde en http://localhost:11434. Inicia Ollama manualmente.

echo.
echo 6. Iniciando Asistente Grafico de Instalacion de Fuente...
"%VENV_PY%" -m fuente.installer_gui
if !errorlevel! neq 0 goto :fail
exit /b 0

:fail
echo.
echo [!] La instalacion no pudo completarse. Revisa los permisos, Python y la salida anterior.
pause
exit /b 1
