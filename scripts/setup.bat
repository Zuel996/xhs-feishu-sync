@echo off
setlocal enabledelayedexpansion

echo ==========================================
echo   xhs-feishu-sync — 一键安装脚本
echo ==========================================
echo.

REM ── 1. 检查 Python ──
echo [1/4] 检查 Python 环境...
python --version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [X] 未找到 Python，请先安装 Python 3.11 及以上版本
    echo     下载地址: https://www.python.org/downloads/
    pause
    exit /b 1
)

for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo   [√] Python %PYVER%

REM 检查 Python 版本号 >= 3.11
for /f "tokens=1,2 delims=." %%a in ("%PYVER%") do (
    set PYMAJOR=%%a
    set PYMINOR=%%b
)
if %PYMAJOR% LSS 3 (
    echo [X] Python 版本过低 (%PYVER%)，需要 3.11 或以上
    pause
    exit /b 1
)
if %PYMAJOR% EQU 3 if %PYMINOR% LSS 11 (
    echo [X] Python 版本过低 (%PYVER%)，需要 3.11 或以上
    pause
    exit /b 1
)

REM ── 2. 安装依赖 ──
echo.
echo [2/4] 安装项目依赖...
pip install -e . >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [X] 依赖安装失败，请检查网络连接后重试
    pause
    exit /b 1
)
echo   [√] 依赖安装完成

REM ── 3. 配置文件 ──
echo.
echo [3/4] 检查配置文件...

REM .env
if not exist .env (
    if exist .env.example (
        copy .env.example .env >nul
        echo   [√] 已从 .env.example 创建 .env
        echo   [!] 请编辑 .env 文件，填入飞书应用凭证
    ) else (
        echo   [!] 未找到 .env.example，请手动创建 .env 文件
    )
) else (
    echo   [√] .env 已存在，跳过
)

REM Chrome 路径检测
set CHROME=
if exist "C:\Program Files\Google\Chrome\Application\chrome.exe" set CHROME=C:\Program Files\Google\Chrome\Application\chrome.exe
if not defined CHROME if exist "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" set CHROME=C:\Program Files (x86)\Google\Chrome\Application\chrome.exe
if not defined CHROME if exist "%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe" set CHROME=%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe

if defined CHROME (
    echo   [√] Chrome: !CHROME!
) else (
    echo   [!] 未检测到 Chrome 浏览器（仅 CSV 模式不受影响）
)

REM accounts.yaml
findstr /C:"your_account" config\accounts.yaml >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo   [!] config\accounts.yaml 中账号信息仍为占位符，请编辑填入真实账号
) else (
    echo   [√] accounts.yaml 已配置
)

REM ── 4. 初始化数据库 ──
echo.
echo [4/4] 初始化数据库和飞书表...
xhs-feishu setup
if %ERRORLEVEL% NEQ 0 (
    echo [!] setup 部分完成（飞书表可能需要配置 .env 后才能创建）
) else (
    echo   [√] 初始化完成
)

REM ── 完成 ──
echo.
echo ==========================================
echo   安装完成！
echo ==========================================
echo.
echo   下一步:
echo   1. 编辑 .env 填入飞书凭证
echo   2. 编辑 config\accounts.yaml 填入小红书账号
echo   3. xhs-feishu test-feishu  验证飞书连接
echo   4. scripts\start_chrome.bat  启动 Chrome 调试模式
echo   5. xhs-feishu run  首次采集同步
echo.
pause
