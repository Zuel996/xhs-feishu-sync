@echo off
REM === XHS Data Sync - Chrome Debug Mode Launcher ===
REM Close all Chrome windows before running this script.
REM First use: log in to creator.xiaohongshu.com in the opened browser.

REM Auto-discover Chrome installation path
set CHROME=
if exist "C:\Program Files\Google\Chrome\Application\chrome.exe" set CHROME=C:\Program Files\Google\Chrome\Application\chrome.exe
if not defined CHROME if exist "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" set CHROME=C:\Program Files (x86)\Google\Chrome\Application\chrome.exe
if not defined CHROME if exist "%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe" set CHROME=%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe

if not defined CHROME (
    echo [ERROR] Chrome not found.
    echo Please install Google Chrome, or set CHROME variable to chrome.exe path.
    pause
    exit /b 1
)

set PROFILE_DIR=%USERPROFILE%\chrome-debug-profile
set CDP_PORT=9222
set START_URL=https://creator.xiaohongshu.com

echo ========================================
echo   XHS Data Sync - Chrome Debug Mode
echo ========================================
echo.
echo  Chrome:  %CHROME%
echo  Profile: %PROFILE_DIR%
echo  Port:    %CDP_PORT%
echo  URL:     %START_URL%
echo.
echo After launch, confirm you are logged in to creator.xiaohongshu.com.
echo ========================================
echo.

start "" "%CHROME%" ^
  --remote-debugging-port=%CDP_PORT% ^
  --user-data-dir="%PROFILE_DIR%" ^
  %START_URL%

echo Chrome launched. Waiting 5s to verify connection...
timeout /t 5 /nobreak >nul

curl -s http://localhost:%CDP_PORT%/json/version >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo [OK] CDP port %CDP_PORT% connected
) else (
    echo [WARN] CDP port not responding. Confirm Chrome has fully started.
)

echo.
pause