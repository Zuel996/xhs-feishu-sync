@echo off
setlocal enabledelayedexpansion
title xhs-feishu-sync — 安装器

:: ═══════════════════════════════════════════════════
:: xhs-feishu-sync 一键安装脚本
::
:: 用法: 将 dist/xhs-feishu-server/ + extension/ 放在
::       本脚本同级目录，然后双击运行本脚本。
::
:: 自动完成:
::   1. 复制文件到 %LOCALAPPDATA%\xhs-feishu-sync
::   2. 注册开机自启
::   3. 创建开始菜单快捷方式
::   4. 注册 Chrome 扩展策略
::   5. 启动后端服务
:: ═══════════════════════════════════════════════════

cd /d "%~dp0"

set "INSTALL_DIR=%LOCALAPPDATA%\xhs-feishu-sync"
set "SRC_DIR=%~dp0.."

echo.
echo  ╔══════════════════════════════════════════════════╗
echo  ║     xhs-feishu-sync — 一键安装                  ║
echo  ╚══════════════════════════════════════════════════╝
echo.

:: ── Step 1: Copy files ──
echo  [1/5] 安装文件到 %INSTALL_DIR% ...
if exist "%INSTALL_DIR%" (
    echo         检测到已有安装，正在覆盖更新...
    taskkill /f /im xhs-feishu-server.exe >nul 2>&1
    timeout /t 2 /nobreak >nul
)

mkdir "%INSTALL_DIR%" >nul 2>&1

:: Copy server
if exist "%SRC_DIR%\dist\xhs-feishu-server" (
    robocopy "%SRC_DIR%\dist\xhs-feishu-server" "%INSTALL_DIR%" /E /NFL /NDL /NJH /NJS >nul 2>&1
    echo         后端已安装
) else (
    echo         [警告] 未找到 dist\xhs-feishu-server，请先运行 PyInstaller 打包
)

:: Copy extension
if exist "%SRC_DIR%\extension" (
    if exist "%INSTALL_DIR%\extension" rmdir /s /q "%INSTALL_DIR%\extension"
    robocopy "%SRC_DIR%\extension" "%INSTALL_DIR%\extension" /E /NFL /NDL /NJH /NJS >nul 2>&1
    echo         扩展已安装
) else (
    echo         [警告] 未找到 extension 文件夹
)

:: ── Step 2: Auto-start ──
echo  [2/5] 注册开机自启 ...
powershell -NoProfile -Command ^
  "$reg='HKCU:\Software\Microsoft\Windows\CurrentVersion\Run';" ^
  "New-Item -Path $reg -Force | Out-Null;" ^
  "Set-ItemProperty -Path $reg -Name 'xhs-feishu-sync' -Value '%INSTALL_DIR%\xhs-feishu-server.exe' -Force;"
echo         已设置开机自启

:: ── Step 3: Start Menu shortcut ──
echo  [3/5] 创建开始菜单快捷方式 ...
powershell -NoProfile -Command ^
  "$WshShell = New-Object -ComObject WScript.Shell;" ^
  "$Shortcut = $WshShell.CreateShortcut([Environment]::GetFolderPath('StartMenu') + '\Programs\xhs-feishu-sync.lnk');" ^
  "$Shortcut.TargetPath = '%INSTALL_DIR%\xhs-feishu-server.exe';" ^
  "$Shortcut.WorkingDirectory = '%INSTALL_DIR%';" ^
  "$Shortcut.Description = 'xhs-feishu-sync 后端服务';" ^
  "$Shortcut.Save();"
echo         快捷方式已创建

:: ── Step 4: Chrome Extension Policy ──
echo  [4/5] 注册 Chrome 扩展 ...
set "EXT_ID=pplbaecpijioleoifnbibibegdpgabjb"
set "UPDATE_URL=file:///%INSTALL_DIR:\=/%/extension/update.xml"

:: Create update.xml for the extension
(
echo ^<?xml version='1.0' encoding='UTF-8'?^>
echo ^<gupdate xmlns='http://www.google.com/update2/response' protocol='2.0'^>
echo   ^<app appid='%EXT_ID%'^>
echo     ^<updatecheck codebase='file:///%INSTALL_DIR:\=/%/extension/' version='0.1.0' /^>
echo   ^</app^>
echo ^</gupdate^>
) > "%INSTALL_DIR%\extension\update.xml"

:: Register via Chrome Policy (requires Chrome restart)
powershell -NoProfile -Command ^
  "$policyPath = 'HKLM:\Software\Policies\Google\Chrome\ExtensionInstallForcelist';" ^
  "try {" ^
  "  New-Item -Path $policyPath -Force | Out-Null;" ^
  "  $count = (Get-ItemProperty -Path $policyPath).PSObject.Properties.Name.Count;" ^
  "  Set-ItemProperty -Path $policyPath -Name '$count' -Value '%EXT_ID%;%UPDATE_URL%' -Force;" ^
  "  Write-Host '         扩展策略已注册（需要管理员权限）';" ^
  "} catch {" ^
  "  Write-Host '         注册扩展策略需要管理员权限，请以管理员身份运行本脚本';" ^
  "}"
echo         扩展 ID: %EXT_ID%

:: ── Step 5: Start server ──
echo  [5/5] 启动后端服务 ...
start "" "%INSTALL_DIR%\xhs-feishu-server.exe"
timeout /t 3 /nobreak >nul

:: ── Verify ──
echo.
echo  ═══════════════════════════════════════════════════
echo    ✅ 安装完成！
echo.
echo    后端服务: http://localhost:9527
echo    系统托盘: 右下角查看 xhs-feishu-sync 图标
echo.
echo    如果 Chrome 未自动加载扩展，请：
echo    1. 打开 Chrome → chrome://extensions/
echo    2. 开启「开发者模式」
echo    3. 点击「加载已解压的扩展程序」
echo    4. 选择: %INSTALL_DIR%\extension
echo  ═══════════════════════════════════════════════════
echo.

:: Open Chrome extensions page for convenience
start "" "chrome://extensions/"

pause
