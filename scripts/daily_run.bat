@echo off
REM === 小红书数据采集 — 每日自动运行脚本 ===
REM 配合 Windows 任务计划程序使用：每天 09:00 自动触发
REM 前提：start_chrome.bat 已启动且 Chrome 保持登录状态

echo [%date% %time%] xhs-feishu daily sync start

REM 检查 Chrome CDP 是否运行
curl -s http://localhost:9222/json/version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [错误] Chrome CDP 端口 9222 未响应，请先运行 scripts\start_chrome.bat
    exit /b 1
)

REM 执行采集同步
xhs-feishu run
if %ERRORLEVEL% EQU 0 (
    echo [%date% %time%] sync completed successfully
) else (
    echo [%date% %time%] sync failed with exit code %ERRORLEVEL%
    exit /b %ERRORLEVEL%
)
