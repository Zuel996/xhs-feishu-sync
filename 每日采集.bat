@echo off
cd /d "%~dp0"

C:\Users\LingoAce\AppData\Local\Programs\Python\Python314\Scripts\xhs-feishu.exe run -s bitable

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
