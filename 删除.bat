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

C:\Users\LingoAce\AppData\Local\Programs\Python\Python314\Scripts\xhs-feishu.exe clear --all --confirm

if %errorlevel% neq 0 (
    echo.
    echo   ERROR: Delete failed with code %errorlevel%
    pause
    exit /b %errorlevel%
)

echo.
echo ============================================================
echo   Done. Press any key to close...
echo ============================================================
pause >nul
