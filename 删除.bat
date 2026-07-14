@echo off
cd /d "%~dp0"

echo ============================================================
echo   Delete ALL data from Feishu Bitable
echo ============================================================
echo.
echo   This will delete ALL records from:
echo     - account_summary
echo     - note_metrics
echo     - daily_snapshot
echo     - competitor_comparison
echo   + local SQLite database
echo.
echo   Note: account_manager table is NOT affected.
echo.

set /p CONFIRM="Type YES to confirm delete: "

if /i not "%CONFIRM%"=="YES" (
    echo.
    echo   Cancelled.
    pause
    exit /b
)

echo.
echo   Deleting...
echo.

REM -- Auto-detect Python --
set PYTHON=python
python --version >nul 2>&1
if %ERRORLEVEL% EQU 0 goto :run

REM Try common local install paths (Python 3.11-3.14)
if exist "%LOCALAPPDATA%\Programs\Python\Python314\python.exe" set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python314\python.exe" & goto :run
if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python313\python.exe" & goto :run
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python312\python.exe" & goto :run
if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python311\python.exe" & goto :run

REM Try system-wide install
if exist "C:\Program Files\Python314\python.exe" set "PYTHON=C:\Program Files\Python314\python.exe" & goto :run
if exist "C:\Program Files\Python313\python.exe" set "PYTHON=C:\Program Files\Python313\python.exe" & goto :run
if exist "C:\Program Files\Python312\python.exe" set "PYTHON=C:\Program Files\Python312\python.exe" & goto :run

echo ============================================================
echo   ERROR: Python 3.11+ not found.
echo   Install from https://www.python.org/downloads/
echo ============================================================
pause
exit /b 1

:run
%PYTHON% -m src.cli.main clear --all --confirm

if %errorlevel% neq 0 (
    echo.
    echo ============================================================
    echo   ERROR: Delete failed with code %errorlevel%
    echo ============================================================
    pause
    exit /b %errorlevel%
)

echo.
echo ============================================================
echo   Done. Press any key to close...
echo ============================================================
pause >nul