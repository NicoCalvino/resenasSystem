@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul 2>&1
title Informes de Resenas -- Actualizador

set "APP_DIR=%~dp0"
if "%APP_DIR:~-1%"=="\" set "APP_DIR=%APP_DIR:~0,-1%"

set "PY_EXE=%APP_DIR%\python-portable\python.exe"
set "PIP_EXE=%APP_DIR%\python-portable\Scripts\pip.exe"

echo.
echo  ==================================================
echo   Informes de Resenas - Actualizador
echo  ==================================================
echo.
echo  Actualiza la aplicacion con los archivos nuevos.
echo  Ejecuta este archivo despues de copiar los .py actualizados.
echo.
pause


REM --- Verificar que el entorno portable existe ---------------------------------
if not exist "%PY_EXE%" (
    echo.
    echo  ERROR: No se encontro el entorno de Python portable.
    echo  Ejecuta "instalar.bat" primero.
    echo.
    pause
    exit /b 1
)

if not exist "%APP_DIR%\requirements.txt" (
    echo.
    echo  ERROR: No se encontro requirements.txt.
    echo  Asegurate de haber copiado todos los archivos nuevos.
    echo.
    pause
    exit /b 1
)


REM --- [1/2] Actualizar dependencias -------------------------------------------
echo.
echo  [1/2] Actualizando dependencias Python...
echo.

"%PIP_EXE%" install -r "%APP_DIR%\requirements.txt" --upgrade --quiet
if errorlevel 1 (
    echo.
    echo  ERROR: No se pudieron actualizar las dependencias.
    echo  Verifica tu conexion a internet e intenta de nuevo.
    echo.
    pause
    exit /b 1
)
echo  OK: Dependencias actualizadas.


REM --- [2/2] Verificar Chromium ------------------------------------------------
echo.
echo  [2/2] Verificando Chromium...
echo.

"%PY_EXE%" -m playwright install chromium --quiet
if errorlevel 1 (
    echo  AVISO: No se pudo verificar Chromium.
    echo  La version anterior sigue instalada y deberia funcionar.
) else (
    echo  OK: Chromium verificado y actualizado.
)


REM --- Listo -------------------------------------------------------------------
echo.
echo  ==================================================
echo   Actualizacion completada.
echo  ==================================================
echo.
echo  La aplicacion ya esta lista. Abrila con:
echo.
echo    - El acceso directo "Informes de Resenas" del Escritorio
echo    - O doble clic en "iniciar.vbs" en esta carpeta
echo.
pause
