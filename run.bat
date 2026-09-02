@echo off
chcp 65001 >nul
setlocal

rem ============================================
rem 2240AI 考研助手 — 一键启动脚本 (Windows)
rem 用法: 双击 run.bat 或在终端运行
rem 可覆盖: set APP_ENV=development / set PROCESS_ROLE=web / set PORT=8000
rem ============================================

cd /d "%~dp0backend"

echo ========================================
echo   2240AI 考研助手 — 启动中...
echo ========================================

rem ---- 1. Python 检测 ----
where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] 未找到 Python，请先安装 Python 3.11+
    pause
    exit /b 1
)
echo [INFO] Python:
python --version

rem ---- 2. 运行环境 ----
if not defined APP_ENV set "APP_ENV=development"
if not defined PROCESS_ROLE set "PROCESS_ROLE=all"
if not defined PORT set "PORT=8000"

echo [INFO] APP_ENV=%APP_ENV%
echo [INFO] PROCESS_ROLE=%PROCESS_ROLE%
echo [INFO] PORT=%PORT%

if not exist ".env" (
    echo [WARN] backend\.env 不存在，请先根据 backend\.env.example 创建本地配置。
)

rem ---- 3. 虚拟环境 ----
set "PYTHON_CMD=python"
if not exist ".venv\Scripts\python.exe" (
    echo [INFO] 创建 Python 虚拟环境...
    python -m venv .venv
    if errorlevel 1 (
        echo [WARN] 虚拟环境创建失败，将使用系统 Python。
    ) else (
        set "PYTHON_CMD=.venv\Scripts\python.exe"
        echo [INFO] 虚拟环境已创建。
    )
) else (
    set "PYTHON_CMD=.venv\Scripts\python.exe"
    echo [INFO] 使用已有虚拟环境。
)

rem ---- 4. 安装依赖 ----
echo [INFO] 安装后端依赖...
"%PYTHON_CMD%" -m pip install --quiet --upgrade pip
if errorlevel 1 (
    echo [ERROR] pip 更新失败，请检查网络或 Python 环境。
    pause
    exit /b 1
)

"%PYTHON_CMD%" -m pip install --quiet -r requirements.txt
if errorlevel 1 (
    echo [ERROR] 后端依赖安装失败，未启动服务。
    pause
    exit /b 1
)
echo [INFO] 依赖安装完成。

rem ---- 5. 启动 FastAPI ----
echo.
echo [INFO] 启动 FastAPI...
echo        API: http://127.0.0.1:%PORT%
echo        文档: http://127.0.0.1:%PORT%/docs
echo        停止: Ctrl+C
echo ========================================
echo.

"%PYTHON_CMD%" -m uvicorn app.main:app --host 0.0.0.0 --port %PORT% --reload
set "EXIT_CODE=%ERRORLEVEL%"
pause
exit /b %EXIT_CODE%
