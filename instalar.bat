@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul 2>&1
title Informes de Resenas -- Instalador

REM ============================================================
REM  Configuracion
REM ============================================================
set "PY_VER=3.11.9"
set "PY_URL=https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"

set "APP_DIR=%~dp0"
if "%APP_DIR:~-1%"=="\" set "APP_DIR=%APP_DIR:~0,-1%"

set "PY_DIR=%APP_DIR%\python-portable"
set "PY_EXE=%PY_DIR%\python.exe"
set "PYW_EXE=%PY_DIR%\pythonw.exe"
set "PIP_EXE=%PY_DIR%\Scripts\pip.exe"

REM ============================================================

echo.
echo  ==================================================
echo   Informes de Resenas - Instalador
echo  ==================================================
echo.
echo  Este instalador configura todo automaticamente.
echo  NO necesitas instalar Python ni ningun otro programa.
echo.
echo  Solo necesitas:
echo    - Conexion a internet (para este paso inicial)
echo    - Unos 10 minutos de espera
echo.
echo  Una vez instalada, la app funciona sin internet
echo  (excepto para descargar las resenas).
echo.
pause


REM ============================================================
REM  [1/4] Python portable (instalador completo, incluye tkinter)
REM ============================================================
echo.
echo  [1/4] Configurando Python portable...

if exist "%PYW_EXE%" (
    REM Verificar que tkinter funciona
    "%PY_EXE%" -c "import tkinter" >nul 2>&1
    if not errorlevel 1 (
        echo  OK: Python portable ya esta listo.
        goto :deps
    )
    echo  AVISO: Python portable existe pero le falta tkinter. Reinstalando...
    rmdir /s /q "%PY_DIR%" >nul 2>&1
)

if exist "%APP_DIR%\python_installer.exe" (
    echo  OK: Instalador encontrado localmente, omitiendo descarga.
) else (
    echo  Descargando Python %PY_VER% ...
    echo  (~25 MB)
    echo.

    curl.exe --version >nul 2>&1
    if not errorlevel 1 (
        curl.exe -L --progress-bar -o "%APP_DIR%\python_installer.exe" "%PY_URL%"
    ) else (
        powershell -NoProfile -ExecutionPolicy Bypass -Command "Invoke-WebRequest -Uri '%PY_URL%' -OutFile '%APP_DIR%\python_installer.exe' -UseBasicParsing"
    )
)

if not exist "%APP_DIR%\python_installer.exe" (
    echo.
    echo  ERROR: No se pudo descargar Python.
    echo  Verifica tu conexion a internet e intenta de nuevo.
    pause
    exit /b 1
)

echo.
echo  Instalando Python en la carpeta de la aplicacion...
echo  (esto puede tardar 1-2 minutos)
echo.

"%APP_DIR%\python_installer.exe" /quiet ^
    InstallAllUsers=0 ^
    TargetDir="%PY_DIR%" ^
    Include_launcher=0 ^
    Include_test=0 ^
    Include_doc=0 ^
    PrependPath=0 ^
    Shortcuts=0

del "%APP_DIR%\python_installer.exe" >nul 2>&1

if not exist "%PYW_EXE%" (
    echo.
    echo  ERROR: No se pudo instalar Python.
    pause
    exit /b 1
)
echo  OK: Python instalado en python-portable\


REM ============================================================
REM  [2/4] Dependencias de la app
REM ============================================================
:deps
echo.
echo  [2/4] Instalando dependencias de la aplicacion...
echo  (~2-3 minutos)
echo.

"%PIP_EXE%" install -r "%APP_DIR%\requirements.txt" --quiet
if errorlevel 1 (
    echo.
    echo  ERROR: No se pudieron instalar las dependencias.
    echo  Verifica tu conexion a internet e intenta de nuevo.
    pause
    exit /b 1
)
echo  OK: Dependencias instaladas.


REM ============================================================
REM  [3/4] Chromium
REM ============================================================
echo.
echo  [3/4] Descargando Chromium...
echo  Este es el paso mas largo (~150 MB). No cierres esta ventana.
echo.

"%PY_EXE%" -m playwright install chromium
if errorlevel 1 (
    echo.
    echo  ERROR: No se pudo instalar Chromium.
    echo  Verifica tu conexion a internet e intenta de nuevo.
    pause
    exit /b 1
)
echo.
echo  OK: Chromium instalado.


REM ============================================================
REM  [4/4] Acceso directo en el Escritorio
REM ============================================================
echo.
echo  [4/4] Creando acceso directo en el Escritorio...

if not exist "%APP_DIR%\iniciar.vbs" (
    echo  ERROR: No se encontro iniciar.vbs.
    echo  Asegurate de que todos los archivos de la app esten en esta carpeta.
    pause
    exit /b 1
)

set "VBS_FULL=%APP_DIR%\iniciar.vbs"
set "LNK_PATH=%USERPROFILE%\Desktop\Informes de Resenas.lnk"

powershell -NoProfile -ExecutionPolicy Bypass -Command "$s=(New-Object -COM WScript.Shell).CreateShortcut('%LNK_PATH%'); $s.TargetPath='wscript.exe'; $s.Arguments=chr(34)+'%VBS_FULL%'+chr(34); $s.WorkingDirectory='%APP_DIR%'; $s.Description='Informes de Resenas Negativas'; $s.IconLocation='shell32.dll,13'; $s.Save()" >nul 2>&1

if errorlevel 1 (
    echo  AVISO: No se pudo crear el acceso directo en el Escritorio.
    echo  Podes iniciar la app haciendo doble clic en "iniciar.vbs".
) else (
    echo  OK: Acceso directo creado en el Escritorio.
)


REM ============================================================
REM  Listo
REM ============================================================
echo.
echo  ==================================================
echo   Instalacion completada correctamente.
echo  ==================================================
echo.
echo  Para abrir la aplicacion:
echo.
echo    - Doble clic en "Informes de Resenas" en el Escritorio
echo    - O doble clic en "iniciar.vbs" en esta carpeta
echo.
echo  Ingresa tus credenciales de Rappi la primera vez
echo  que abras la aplicacion.
echo.
echo  Presiona cualquier tecla para cerrar e iniciar la app...
pause >nul

wscript.exe "%VBS_FULL%"
