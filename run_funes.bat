@echo off
cd /d "%~dp0"
if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
)
start "" venv\Scripts\pythonw.exe -m funes.main %*
if %errorlevel% neq 0 (
    echo [!] Error al iniciar Funes. Mostrando detalles de la consola:
    venv\Scripts\python.exe -m funes.main %*
    pause
)
