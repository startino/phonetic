@echo off
setlocal

set SCRIPT_DIR=%~dp0
set ROOT=%SCRIPT_DIR%..
set DIST=%ROOT%\dist

echo Building Windows executable...
cd /d "%ROOT%"
python -m PyInstaller packaging\phonetic.spec --distpath "%DIST%" --workpath "%ROOT%\build\pyinstaller" --clean

if not exist "%DIST%\phonetic" (
    echo ERROR: Build output not found
    exit /b 1
)

echo Creating ZIP...
powershell -Command "Compress-Archive -Path '%DIST%\phonetic' -DestinationPath '%DIST%\phonetic-windows.zip' -Force"

echo Done: %DIST%\phonetic-windows.zip
