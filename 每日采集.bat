@echo off
cd /d "%~dp0"

REM -- 1. Auto-detect Python --
set PYTHON=python
python --version >nul 2>&1
if %ERRORLEVEL% EQU 0 goto :python_ok

REM Try common local install paths (Python 3.11-3.14)
if exist "%LOCALAPPDATA%\Programs\Python\Python314\python.exe" set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python314\python.exe" & goto :python_ok
if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python313\python.exe" & goto :python_ok
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python312\python.exe" & goto :python_ok
if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python311\python.exe" & goto :python_ok

REM Try system-wide install
if exist "C:\Program Files\Python314\python.exe" set "PYTHON=C:\Program Files\Python314\python.exe" & goto :python_ok
if exist "C:\Program Files\Python313\python.exe" set "PYTHON=C:\Program Files\Python313\python.exe" & goto :python_ok
if exist "C:\Program Files\Python312\python.exe" set "PYTHON=C:\Program Files\Python312\python.exe" & goto :python_ok

echo ============================================================
echo   ERROR: Python 3.11+ not found.
echo   Install from https://www.python.org/downloads/
echo   Or run scripts\setup.bat to check your environment.
echo ============================================================
pause
exit /b 1

:python_ok

REM -- 2. Check / Auto-start Chrome CDP --
curl -s http://localhost:9222/json/version >nul 2>&1
if %ERRORLEVEL% EQU 0 goto :cdp_ok

echo Chrome CDP port 9222 not responding. Trying to auto-start Chrome...

REM Auto-detect Chrome
set CHROME=
if exist "C:\Program Files\Google\Chrome\Application\chrome.exe" set "CHROME=C:\Program Files\Google\Chrome\Application\chrome.exe"
if not defined CHROME if exist "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" set "CHROME=C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
if not defined CHROME if exist "%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe" set "CHROME=%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"

if not defined CHROME (
    echo ============================================================
    echo   ERROR: Chrome not found. Please install Chrome first,
    echo   or switch to CSV-only mode in config/settings.yaml.
    echo ============================================================
    pause
    exit /b 1
)

echo   Chrome: %CHROME%
echo   Starting Chrome with remote debugging on port 9222...
echo   (Log in to creator.xiaohongshu.com if this is your first run)
start "" "%CHROME%" --remote-debugging-port=9222 --user-data-dir="%USERPROFILE%\chrome-debug-profile" https://creator.xiaohongshu.com

REM Wait up to 30 seconds for CDP port to become available
set /a WAIT_COUNT=0
:wait_cdp
timeout /t 2 /nobreak >nul
set /a WAIT_COUNT+=1
curl -s http://localhost:9222/json/version >nul 2>&1
if %ERRORLEVEL% EQU 0 goto :cdp_ok
if %WAIT_COUNT% LSS 15 goto :wait_cdp

echo ============================================================
echo   ERROR: Chrome started but CDP port not responding.
echo   Make sure Chrome is not already running in normal mode.
echo   Close all Chrome windows and try again.
echo ============================================================
pause
exit /b 1

:cdp_ok
echo Chrome CDP connected.

REM -- 3. Run collection --
%PYTHON% -m src.cli.main run -s bitable

if %errorlevel% neq 0 (
    echo.
    echo ============================================================
    echo   ERROR: Collection failed with code %errorlevel%
    echo ============================================================
    pause
    exit /b %errorlevel%
)

echo.
echo ============================================================
echo   Collection done. Press any key to close...
echo ============================================================
pause >nul