@echo off
setlocal
title xhs-feishu-sync — Package

cd /d "%~dp0.."

set "VERSION=0.1.0"
set "PACKAGE_NAME=xhs-feishu-sync-v%VERSION%"
set "BUILD_DIR=build\package\%PACKAGE_NAME%"

echo.
echo  ====================================================
echo    Package — xhs-feishu-sync v%VERSION%
echo  ====================================================
echo.

:: ── Check prerequisites ──
if not exist "dist\xhs-feishu-server\xhs-feishu-server.exe" (
    echo  [ERROR] dist\xhs-feishu-server\xhs-feishu-server.exe not found
    echo          Run PyInstaller first: pyinstaller xhs-feishu-server.spec
    pause
    exit /b 1
)

if not exist "extension\manifest.json" (
    echo  [ERROR] extension\manifest.json not found
    pause
    exit /b 1
)

:: ── Build package directory ──
echo  [1/3] Building package directory ...
if exist "%BUILD_DIR%" rmdir /s /q "%BUILD_DIR%"
mkdir "%BUILD_DIR%" >nul 2>&1

:: Copy server
robocopy "dist\xhs-feishu-server" "%BUILD_DIR%\xhs-feishu-server" /E /NFL /NDL /NJH /NJS >nul
echo        Server copied

:: Copy extension
robocopy "extension" "%BUILD_DIR%\extension" /E /NFL /NDL /NJH /NJS >nul
echo        Extension copied

:: Copy installer
copy "scripts\install.bat" "%BUILD_DIR%\install.bat" >nul
echo        Installer copied

:: ── Create README ──
echo  [2/3] Generating readme ...
(
echo # xhs-feishu-sync v%VERSION%
echo.
echo ## Installation
echo.
echo 1. Right-click `install.bat` ^-^> Run as administrator
echo 2. Wait for installation to complete
echo 3. Chrome will auto-open the extensions page
echo 4. Enable "Developer mode" ^-^> "Load unpacked" ^-^> Select: %%LOCALAPPDATA%%\xhs-feishu-sync\extension
echo 5. Click the extension icon ^-^> Fill Feishu credentials ^-^> Add accounts ^-^> Click "Start"
echo.
echo ## Daily Use
echo.
echo - Backend auto-starts on boot (system tray icon)
echo - Click extension icon ^-^> "Start" ^-^> Auto-collect from creator.xiaohongshu.com
echo - Or wait for scheduled daily collection at 10:00 AM
echo.
echo ## Uninstall
echo.
echo 1. Close xhs-feishu-sync from system tray
echo 2. Delete folder: %%LOCALAPPDATA%%\xhs-feishu-sync
echo 3. Remove extension from chrome://extensions/
) > "%BUILD_DIR%\README.md"
echo        Readme generated

:: ── Create ZIP ──
echo  [3/3] Creating zip ...
powershell -NoProfile -Command ^
  "Compress-Archive -Path '%BUILD_DIR%\*' -DestinationPath 'dist\%PACKAGE_NAME%.zip' -Force;"
echo        Package created: dist\%PACKAGE_NAME%.zip

:: ── Done ──
echo.
echo  ====================================================
echo    Package complete!
echo.
echo    Distribution: dist\%PACKAGE_NAME%.zip
echo    User flow: Extract ^^^> Right-click install.bat ^^^> Run as administrator
echo  ====================================================
echo.

pause
