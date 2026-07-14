@echo off
REM === 小红书数据采集 — Chrome 调试模式启动脚本 ===
REM 关闭所有 Chrome 窗口后运行此脚本
REM 首次使用需在打开的浏览器中登录 creator.xiaohongshu.com

REM 自动发现 Chrome 安装路径
set CHROME=
if exist "C:\Program Files\Google\Chrome\Application\chrome.exe" set CHROME=C:\Program Files\Google\Chrome\Application\chrome.exe
if not defined CHROME if exist "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" set CHROME=C:\Program Files (x86)\Google\Chrome\Application\chrome.exe
if not defined CHROME if exist "%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe" set CHROME=%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe

if not defined CHROME (
    echo [错误] 未找到 Chrome 浏览器。
    echo 请确保已安装 Google Chrome，或手动设置 CHROME 变量指向 chrome.exe。
    pause
    exit /b 1
)

set PROFILE_DIR=%USERPROFILE%\chrome-debug-profile
set CDP_PORT=9222
set START_URL=https://creator.xiaohongshu.com

echo ========================================
echo   小红书数据采集 — Chrome 调试模式
echo ========================================
echo.
echo  Chrome: %CHROME%
echo  Profile: %PROFILE_DIR%
echo  Port: %CDP_PORT%
echo  URL: %START_URL%
echo.
echo 启动后请在浏览器中确认已登录创作者中心。
echo ========================================
echo.

start "" "%CHROME%" ^
  --remote-debugging-port=%CDP_PORT% ^
  --user-data-dir="%PROFILE_DIR%" ^
  %START_URL%

echo Chrome 已启动。等待 5 秒后检查连接...
timeout /t 5 /nobreak >nul

REM 验证 CDP 端口是否可用
curl -s http://localhost:%CDP_PORT%/json/version >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo [√] CDP 端口 %CDP_PORT% 连接正常
) else (
    echo [!] CDP 端口未响应，请确认 Chrome 已完全启动
)

echo.
pause
