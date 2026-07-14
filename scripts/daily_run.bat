@echo off
REM === XHS Data Sync - Daily Auto-Run Script ===
REM Use with Windows Task Scheduler: trigger daily at 09:00
REM Prerequisite: start_chrome.bat is running and Chrome is logged in

echo [%date% %time%] xhs-feishu daily sync start

REM -- Check Chrome CDP --
curl -s http://localhost:9222/json/version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Chrome CDP port 9222 not responding. Run scripts\start_chrome.bat first.
    exit /b 1
)

REM -- Auto-detect Python --
set PYTHON=python
python --version >nul 2>&1
if %ERRORLEVEL% EQU 0 goto :run

if exist "%LOCALAPPDATA%\Programs\Python\Python314\python.exe" set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python314\python.exe" & goto :run
if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python313\python.exe" & goto :run
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python312\python.exe" & goto :run
if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python311\python.exe" & goto :run
if exist "C:\Program Files\Python314\python.exe" set "PYTHON=C:\Program Files\Python314\python.exe" & goto :run
if exist "C:\Program Files\Python313\python.exe" set "PYTHON=C:\Program Files\Python313\python.exe" & goto :run

echo [ERROR] Python not found
exit /b 1

:run
%PYTHON% -m src.cli.main run

if %ERRORLEVEL% EQU 0 (
    echo [%date% %time%] sync completed successfully
) else (
    echo [%date% %time%] sync failed with exit code %ERRORLEVEL%
    exit /b %ERRORLEVEL%
)