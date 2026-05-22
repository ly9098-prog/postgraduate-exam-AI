@echo off
chcp 65001 >nul
rem ============================================
rem 2240AI 考研助手 — 一键启动脚本 (Windows)
rem 用法: 双击 run.bat 或在终端运行
rem ============================================

cd /d "%~dp0backend"

echo ========================================
echo   2240AI 考研助手 — 启动中...
echo ========================================

rem ---- 1. Python 检测 ----
where python >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo ❌ 未找到 Python，请先安装 Python 3.11+
    pause
    exit /b 1
)
echo ✅ Python:
python --version

rem ---- 2. 虚拟环境 ----
if not exist ".venv" (
    echo 📦 创建虚拟环境...
    python -m venv .venv
    if %ERRORLEVEL% neq 0 (
        echo ⚠️  虚拟环境创建失败，将使用系统 Python
        goto :install_deps
    )
    echo ✅ 虚拟环境已创建
) else (
    echo ✅ 虚拟环境已存在
)

call .venv\Scripts\activate.bat 2>nul
if %ERRORLEVEL% neq 0 (
    echo ⚠️  无法激活虚拟环境，将使用系统 Python
)

:install_deps
echo 📦 安装依赖...
python -m pip install --quiet --upgrade pip 2>nul
pip install --quiet -r requirements.txt 2>nul || (
    rem 如果安装失败（PEP 668），尝试 --break-system-packages
    pip install --quiet --break-system-packages -r requirements.txt
)
if %ERRORLEVEL% neq 0 (
    echo ⚠️  部分依赖安装可能失败，尝试启动...
) else (
    echo ✅ 依赖安装完成
)

rem ---- 3. 启动 FastAPI ----
echo.
echo 🚀 启动服务...
echo    访问地址: http://127.0.0.1:8000
echo    API 文档: http://127.0.0.1:8000/docs
echo    停止服务: Ctrl+C
echo ========================================
echo.

uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
pause
