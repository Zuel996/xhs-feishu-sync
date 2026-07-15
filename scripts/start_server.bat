@echo off
cd /d "%~dp0\.."

title xhs-feishu-server

REM -- Auto-detect Python --
set PYTHON=python
python --version >nul 2>&1
if %ERRORLEVEL% EQU 0 goto :start

if exist "%LOCALAPPDATA%\Programs\Python\Python314\python.exe" set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python314\python.exe" & goto :start
if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python313\python.exe" & goto :start
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python312\python.exe" & goto :start
if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python311\python.exe" & goto :start

echo ERROR: Python 3.11+ not found.
pause
exit /b 1

:start
echo ============================================================
echo   xhs-feishu-sync — API Server
echo ============================================================
echo.
echo   Server running at http://localhost:9527
echo   Press Ctrl+C to stop
echo.
%PYTHON% -m uvicorn src.api.server:app --host 127.0.0.1 --port 9527 --log-level info

pause
