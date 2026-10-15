@echo off
title CENTINELA UPS - Servidor Web y Monitor
cd /d "%~dp0"

echo ========================================================
echo   CENTINELA UPS - Servidor Web y Monitor Multi-UPS
echo ========================================================
echo.

:: 1. Si el servidor ya esta en ejecucion en el puerto 8001, solo abrir el navegador
netstat -ano | findstr :8001 | findstr LISTENING >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo [i] Centinela ya se encuentra activo en el puerto 8001.
    echo [i] Abriendo el panel en su navegador web...
    start "" http://localhost:8001/
    echo.
    echo Pulse cualquier tecla para cerrar esta ventana...
    pause >nul
    exit /b
)

echo Iniciando servidor y monitor...
echo Se abrira automaticamente en su navegador: http://localhost:8001/
echo.

:: 2. Limpiar bloqueo de sesion anterior para asegurar apertura en esta ejecucion
if exist "%TEMP%\centinela_browser_opened.lock" del /f /q "%TEMP%\centinela_browser_opened.lock" >nul 2>&1

:: 3. Activar bandera de apertura de navegador
set CENTINELA_OPEN_BROWSER=1

:: 4. Ejecutar servidor usando el entorno virtual si existe, o python del sistema
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" manage.py runserver 8001 --open-browser
) else (
    python manage.py runserver 8001 --open-browser
)

pause
