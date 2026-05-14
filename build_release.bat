@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo === DiskVision: install deps (dev) ===
python -m pip install -r requirements-dev.txt
if errorlevel 1 goto :fail

echo === Generate logo assets ===
python tools\make_icons.py
if errorlevel 1 goto :fail

echo === PyInstaller (onefile) ===
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
python -m PyInstaller --noconfirm DiskVision.spec
if errorlevel 1 goto :fail

if not exist "dist\DiskVision.exe" (
  echo *** dist\DiskVision.exe not found ***
  goto :fail
)

echo === Copy to DiskVision_Release ===
set "REL=..\DiskVision_Release"
if not exist "%REL%" mkdir "%REL%"
copy /Y "dist\DiskVision.exe" "%REL%\"
echo.
echo OK:  %REL%\DiskVision.exe
echo.
pause
exit /b 0

:fail
echo.
echo BUILD FAILED
pause
exit /b 1
