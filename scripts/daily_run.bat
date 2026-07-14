@echo off
REM === XHS Data Sync — Daily Auto-Run Script ===
REM Use with Windows Task Scheduler: trigger daily at 09:00
REM Prerequisite: start_chrome.bat is running and Chrome is logged in

echo [%date% %time%] xhs-feishu daily sync start

REM Check if Chrome CDP is alive
curl -s http://localhost:9222/json/version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Chrome CDP port 9222 not responding. Run scripts\start_chrome.bat first.
    exit /b 1
)

REM Run sync
xhs-feishu run
if %ERRORLEVEL% EQU 0 (
    echo [%date% %time%] sync completed successfully
) else (
    echo [%date% %time%] sync failed with exit code %ERRORLEVEL%
    exit /b %ERRORLEVEL%
)
