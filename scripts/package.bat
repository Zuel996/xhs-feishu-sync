@echo off
setlocal
title xhs-feishu-sync — 打包分发

cd /d "%~dp0.."

set "VERSION=0.1.0"
set "PACKAGE_NAME=xhs-feishu-sync-v%VERSION%"
set "BUILD_DIR=build\package\%PACKAGE_NAME%"

echo.
echo  ╔══════════════════════════════════════════════════╗
echo  ║     打包分发 — xhs-feishu-sync v%VERSION%         ║
echo  ╚══════════════════════════════════════════════════╝
echo.

:: ── Check prerequisites ──
if not exist "dist\xhs-feishu-server\xhs-feishu-server.exe" (
    echo  [ERROR] 未找到 dist\xhs-feishu-server\xhs-feishu-server.exe
    echo          请先运行: pyinstaller --onedir --noconsole ...
    pause
    exit /b 1
)

if not exist "extension\manifest.json" (
    echo  [ERROR] 未找到 extension\manifest.json
    pause
    exit /b 1
)

:: ── Build package directory ──
echo  [1/3] 构建打包目录 ...
if exist "%BUILD_DIR%" rmdir /s /q "%BUILD_DIR%"
mkdir "%BUILD_DIR%" >nul 2>&1

:: Copy server
robocopy "dist\xhs-feishu-server" "%BUILD_DIR%\xhs-feishu-server" /E /NFL /NDL /NJH /NJS >nul
echo         后端已复制

:: Copy extension
robocopy "extension" "%BUILD_DIR%\extension" /E /NFL /NDL /NJH /NJS >nul
echo         扩展已复制

:: Copy installer
copy "scripts\install.bat" "%BUILD_DIR%\install.bat" >nul
echo         安装脚本已复制

:: ── Create README ──
echo  [2/3] 生成说明文件 ...
(
echo # xhs-feishu-sync v%VERSION%
echo.
echo ## 安装步骤
echo.
echo 1. 右键 `install.bat` → 以管理员身份运行
echo 2. 等待安装完成
echo 3. Chrome 会自动打开扩展管理页面
echo 4. 开启「开发者模式」→「加载已解压的扩展程序」→ 选择 `%LOCALAPPDATA%\xhs-feishu-sync\extension`
echo 5. 点击 Chrome 工具栏的插件图标 → 填写飞书凭证 → 添加账号 → 点击「开始」
echo.
echo ## 日常使用
echo.
echo - 后端会在开机时自动启动（系统托盘图标）
echo - 点击插件图标 → 点「开始」→ 自动打开小红书创作者中心采集数据
echo - 也可以每天等它自动采集（每日 10:00）
echo.
echo ## 卸载
echo.
echo 1. 关闭系统托盘中的 xhs-feishu-sync
echo 2. 删除文件夹: %LOCALAPPDATA%\xhs-feishu-sync
echo 3. Chrome 扩展管理页面移除扩展
) > "%BUILD_DIR%\安装说明.md"
echo         说明文件已生成

:: ── Create ZIP ──
echo  [3/3] 创建压缩包 ...
powershell -NoProfile -Command ^
  "Compress-Archive -Path '%BUILD_DIR%\*' -DestinationPath 'dist\%PACKAGE_NAME%.zip' -Force;"
echo         压缩包已创建: dist\%PACKAGE_NAME%.zip

:: ── Done ──
echo.
echo  ═══════════════════════════════════════════════════
echo   ✅ 打包完成！
echo.
echo     分发文件: dist\%PACKAGE_NAME%.zip
echo     用户只需: 解压 → 右击 install.bat → 以管理员身份运行
echo  ═══════════════════════════════════════════════════
echo.

pause
