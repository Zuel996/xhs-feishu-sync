@echo off
setlocal enabledelayedexpansion

echo ==========================================
echo   xhs-feishu-sync — One-Click Setup
echo ==========================================
echo.

REM ── 1. Check Python ──
echo [1/4] Checking Python environment...
python --version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [X] Python not found. Please install Python 3.11+ first.
    echo     Download: https://www.python.org/downloads/
    pause
    exit /b 1
)

for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo   [OK] Python %PYVER%

for /f "tokens=1,2 delims=." %%a in ("%PYVER%") do (
    set PYMAJOR=%%a
    set PYMINOR=%%b
)
if %PYMAJOR% LSS 3 (
    echo [X] Python version too old (%PYVER%), need 3.11+
    pause
    exit /b 1
)
if %PYMAJOR% EQU 3 if %PYMINOR% LSS 11 (
    echo [X] Python version too old (%PYVER%), need 3.11+
    pause
    exit /b 1
)

REM ── 2. Install dependencies ──
echo.
echo [2/4] Installing project dependencies...
pip install -e . >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [X] Dependency install failed. Check network and retry.
    pause
    exit /b 1
)
echo   [OK] Dependencies installed

REM ── 3. Config files ──
echo.
echo [3/4] Checking config files...

if not exist .env (
    if exist .env.example (
        copy .env.example .env >nul
        echo   [OK] Created .env from .env.example
        echo   [!!] Edit .env and fill in your Feishu app credentials
    ) else (
        echo   [!!] .env.example not found. Create .env manually.
    )
) else (
    echo   [OK] .env exists, skipping
)

REM Chrome path detection
set CHROME=
if exist "C:\Program Files\Google\Chrome\Application\chrome.exe" set CHROME=C:\Program Files\Google\Chrome\Application\chrome.exe
if not defined CHROME if exist "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" set CHROME=C:\Program Files (x86)\Google\Chrome\Application\chrome.exe
if not defined CHROME if exist "%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe" set CHROME=%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe

if defined CHROME (
    echo   [OK] Chrome: !CHROME!
) else (
    echo   [!!] Chrome not detected (CSV-only mode unaffected)
)

REM accounts.yaml check
findstr /C:"your_account" config\accounts.yaml >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo   [!!] accounts.yaml still has placeholder. Edit and fill in real accounts.
) else (
    echo   [OK] accounts.yaml configured
)

REM ── 4. Initialize database ──
echo.
echo [4/4] Initializing database and Feishu tables...
xhs-feishu setup
if %ERRORLEVEL% NEQ 0 (
    echo [!!] Setup partially completed (Feishu tables may need .env config)
) else (
    echo   [OK] Initialization complete
)

REM ── Done ──
echo.
echo ==========================================
echo   Setup Complete!
echo ==========================================
echo.
echo   Next steps:
echo   1. Edit .env with Feishu credentials
echo   2. Edit config\accounts.yaml with XHS accounts
echo   3. xhs-feishu test-feishu   Verify Feishu connection
echo   4. scripts\start_chrome.bat  Start Chrome debug mode
echo   5. xhs-feishu run  First data sync
echo.
pause
