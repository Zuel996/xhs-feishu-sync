@echo off
setlocal enabledelayedexpansion
title xhs-feishu-sync Installer

cd /d "%~dp0"

:: Detect mode: packaged (same dir) or dev (parent of scripts/)
if exist "%~dp0xhs-feishu-server\" (
    set "SRC_DIR=%~dp0"
) else (
    set "SRC_DIR=%~dp0.."
)

:: In dev mode, server is in dist/ subfolder
if exist "%SRC_DIR%\dist\xhs-feishu-server\" (
    set "SERVER_SRC=%SRC_DIR%\dist\xhs-feishu-server"
) else (
    set "SERVER_SRC=%SRC_DIR%\xhs-feishu-server"
)

set "EXT_SRC=%SRC_DIR%\extension"
set "INSTALL_DIR=%LOCALAPPDATA%\xhs-feishu-sync"

echo.
echo  +--------------------------------------------------+
echo  ^|   xhs-feishu-sync - One-Click Installer          ^|
echo  +--------------------------------------------------+
echo.

:: Step 1: Copy files
echo  [1/5] Installing files to %INSTALL_DIR% ...
if exist "%INSTALL_DIR%" (
    echo        Existing installation detected, updating...
    taskkill /f /im xhs-feishu-server.exe >nul 2>&1
    timeout /t 2 /nobreak >nul
)

mkdir "%INSTALL_DIR%" >nul 2>&1

:: Copy server
if exist "%SERVER_SRC%\" (
    robocopy "%SERVER_SRC%" "%INSTALL_DIR%" /E /NFL /NDL /NJH /NJS >nul 2>&1
    echo        Backend installed
) else (
    echo        [WARNING] Server not found: %SERVER_SRC%
)

:: Copy extension
if exist "%EXT_SRC%\" (
    if exist "%INSTALL_DIR%\extension" rmdir /s /q "%INSTALL_DIR%\extension"
    robocopy "%EXT_SRC%" "%INSTALL_DIR%\extension" /E /NFL /NDL /NJH /NJS >nul 2>&1
    echo        Extension installed
) else (
    echo        [WARNING] Extension folder not found: %EXT_SRC%
)

:: Copy .env if missing (with placeholder values)
if not exist "%INSTALL_DIR%\.env" (
    echo # xhs-feishu-sync Environment Configuration > "%INSTALL_DIR%\.env"
    echo # 飞书凭证通过 Chrome 插件界面配置，此处保留默认值即可 >> "%INSTALL_DIR%\.env"
    echo FEISHU_APP_ID= >> "%INSTALL_DIR%\.env"
    echo FEISHU_APP_SECRET= >> "%INSTALL_DIR%\.env"
    echo FEISHU_BITABLE_APP_TOKEN= >> "%INSTALL_DIR%\.env"
    echo FEISHU_BOT_WEBHOOK_URL= >> "%INSTALL_DIR%\.env"
    echo XHS_APP_KEY= >> "%INSTALL_DIR%\.env"
    echo XHS_APP_SECRET= >> "%INSTALL_DIR%\.env"
    echo CDP_ENDPOINT=http://localhost:9222 >> "%INSTALL_DIR%\.env"
    echo ACCOUNT_SOURCE=auto >> "%INSTALL_DIR%\.env"
    echo        .env file created
)

:: Ensure config/ exists in both root and _internal/ (PyInstaller path resolution)
if exist "%SRC_DIR%\config\" (
    if not exist "%INSTALL_DIR%\config\" mkdir "%INSTALL_DIR%\config"
    robocopy "%SRC_DIR%\config" "%INSTALL_DIR%\config" /E /NFL /NDL /NJH /NJS >nul 2>&1
    if not exist "%INSTALL_DIR%\_internal\config\" mkdir "%INSTALL_DIR%\_internal\config"
    robocopy "%SRC_DIR%\config" "%INSTALL_DIR%\_internal\config" /E /NFL /NDL /NJH /NJS >nul 2>&1
    echo        Config files installed
)

:: Step 2: Auto-start
echo  [2/5] Registering auto-start on boot ...
powershell -NoProfile -Command ^
  "$reg='HKCU:\Software\Microsoft\Windows\CurrentVersion\Run';" ^
  "New-Item -Path $reg -Force | Out-Null;" ^
  "Set-ItemProperty -Path $reg -Name 'xhs-feishu-sync' -Value '%INSTALL_DIR%\xhs-feishu-server.exe' -Force;"
echo        Auto-start registered

:: Step 3: Start Menu shortcut
echo  [3/5] Creating Start Menu shortcut ...
powershell -NoProfile -Command ^
  "$WshShell = New-Object -ComObject WScript.Shell;" ^
  "$Shortcut = $WshShell.CreateShortcut([Environment]::GetFolderPath('StartMenu') + '\Programs\xhs-feishu-sync.lnk');" ^
  "$Shortcut.TargetPath = '%INSTALL_DIR%\xhs-feishu-server.exe';" ^
  "$Shortcut.WorkingDirectory = '%INSTALL_DIR%';" ^
  "$Shortcut.Description = 'xhs-feishu-sync Backend Service';" ^
  "$Shortcut.Save();"
echo        Shortcut created

:: Step 4: Chrome Extension Policy
echo  [4/5] Registering Chrome extension ...
set "EXT_ID=pplbaecpijioleoifnbibibegdpgabjb"
set "UPDATE_URL=file:///%INSTALL_DIR:\=/%/extension/update.xml"

:: Create update.xml
(
echo ^<?xml version='1.0' encoding='UTF-8'?^>
echo ^<gupdate xmlns='http://www.google.com/update2/response' protocol='2.0'^>
echo   ^<app appid='%EXT_ID%'^>
echo     ^<updatecheck codebase='file:///%INSTALL_DIR:\=/%/extension/' version='0.1.0' /^>
echo   ^</app^>
echo ^</gupdate^>
) > "%INSTALL_DIR%\extension\update.xml"

:: Register via Chrome Policy (requires admin)
powershell -NoProfile -Command ^
  "$ErrorActionPreference = 'Stop';" ^
  "try {" ^
  "  $policyPath = 'HKLM:\Software\Policies\Google\Chrome\ExtensionInstallForcelist';" ^
  "  New-Item -Path $policyPath -Force -ErrorAction Stop | Out-Null;" ^
  "  $count = (Get-ItemProperty -Path $policyPath -ErrorAction Stop).PSObject.Properties.Name.Count;" ^
  "  Set-ItemProperty -Path $policyPath -Name '$count' -Value '%EXT_ID%;%UPDATE_URL%' -Force -ErrorAction Stop;" ^
  "  Write-Host '       Extension policy registered (admin required)';" ^
  "} catch {" ^
  "  Write-Host '       Extension policy requires admin privileges. Please run as administrator.';" ^
  "}"
echo        Extension ID: %EXT_ID%

:: Step 5: Start server
echo  [5/5] Starting backend service ...
powershell -NoProfile -Command "Start-Process -FilePath '%INSTALL_DIR%\xhs-feishu-server.exe' -WorkingDirectory '%INSTALL_DIR%' -NoNewWindow"

:: Wait and verify server started (retry up to 8 times, ~10 seconds)
set "HEALTH_OK=0"
for /L %%i in (1,1,8) do (
    timeout /t 1 /nobreak >nul
    powershell -NoProfile -Command ^
      "try { $r = Invoke-RestMethod -Uri 'http://localhost:9527/health' -TimeoutSec 2; if ($r.status -eq 'ok') { exit 0 } else { exit 1 } } catch { exit 1 }" >nul 2>&1
    if !errorlevel! equ 0 (
        set "HEALTH_OK=1"
        echo        Backend started successfully (attempt %%i^)
        goto :server_ready
    )
)
:server_ready

if "!HEALTH_OK!" equ "0" (
    echo        [WARNING] Backend may still be starting — check http://localhost:9527/health
)

:: Done
echo.
echo  +--------------------------------------------------+
echo  ^|   Install complete!                              ^|
echo  ^|                                                  ^|
echo  ^|   Backend API: http://localhost:9527             ^|
echo  ^|   System tray: check bottom-right corner         ^|
echo  ^|                                                  ^|
echo  ^|   If Chrome extension is not auto-loaded:        ^|
echo  ^|   1. Open Chrome -^> chrome://extensions/         ^|
echo  ^|   2. Enable Developer mode                       ^|
echo  ^|   3. Click Load unpacked                         ^|
echo  ^|   4. Select: %INSTALL_DIR%\extension             ^|
echo  +--------------------------------------------------+
echo.

start chrome "chrome://extensions/"
pause
