@echo off
chcp 65001 >nul
setlocal EnableExtensions

rem ============================================
rem 2240AI local backend launcher (Windows)
rem Usage: double-click run.bat or run it from a terminal
rem Overrides: set APP_ENV=development / set PROCESS_ROLE=web / set PORT=8000
rem Skip dependency installation: set SKIP_DEP_INSTALL=1
rem ============================================

set "PROJECT_ROOT=%~dp0"
set "BACKEND_DIR=%PROJECT_ROOT%backend"
if not exist "%BACKEND_DIR%\app\main.py" (
    echo [ERROR] Backend directory or app\main.py not found: %BACKEND_DIR%
    pause
    exit /b 1
)
cd /d "%BACKEND_DIR%"
if errorlevel 1 (
    echo [ERROR] Cannot enter backend directory: %BACKEND_DIR%
    pause
    exit /b 1
)

echo ========================================
echo   2240AI backend is starting...
echo ========================================

rem ---- 1. Check Python ----
where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python was not found. Install Python 3.11 or newer.
    pause
    exit /b 1
)
python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python 3.11 or newer is required.
    python --version
    pause
    exit /b 1
)

rem ---- 2. Runtime settings ----
if not defined APP_ENV set "APP_ENV=development"
if not defined PROCESS_ROLE set "PROCESS_ROLE=all"
if not defined PORT set "PORT=8000"

echo [INFO] APP_ENV=%APP_ENV%
echo [INFO] PROCESS_ROLE=%PROCESS_ROLE%
echo [INFO] PORT=%PORT%

if not exist ".env" (
    echo [WARN] backend\.env is missing. Create it from backend\.env.example first.
)
if not exist "requirements.txt" (
    echo [ERROR] backend\requirements.txt was not found.
    pause
    exit /b 1
)

rem ---- 3. Virtual environment ----
set "PYTHON_CMD=python"
if exist ".venv\Scripts\python.exe" goto :use_existing_venv

echo [INFO] Creating Python virtual environment...
python -m venv .venv
if errorlevel 1 goto :use_system_python
set "PYTHON_CMD=%CD%\.venv\Scripts\python.exe"
echo [INFO] Virtual environment created.
goto :python_ready

:use_existing_venv
set "PYTHON_CMD=%CD%\.venv\Scripts\python.exe"
"%PYTHON_CMD%" -c "import sys" >nul 2>&1
if errorlevel 1 goto :use_system_python
echo [INFO] Using existing virtual environment.
goto :python_ready

:use_system_python
set "PYTHON_CMD=python"
echo [WARN] Virtual environment is unavailable. Using system Python.

:python_ready
"%PYTHON_CMD%" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python 3.11 or newer is required.
    "%PYTHON_CMD%" --version
    pause
    exit /b 1
)
echo [INFO] Python version:
"%PYTHON_CMD%" --version

rem ---- 4. Install dependencies ----
if /i "%SKIP_DEP_INSTALL%"=="1" goto :skip_dependency_install
echo [INFO] Installing backend dependencies...
"%PYTHON_CMD%" -m pip install --quiet --upgrade pip
if errorlevel 1 (
    echo [ERROR] pip update failed. Check the network or Python environment.
    pause
    exit /b 1
)

"%PYTHON_CMD%" -m pip install --quiet -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Backend dependency installation failed. Server not started.
    pause
    exit /b 1
)
echo [INFO] Backend dependencies installed.
goto :ensure_docx

:skip_dependency_install
echo [INFO] SKIP_DEP_INSTALL=1. Skipping dependency installation.
goto :ensure_docx

:ensure_docx
"%PYTHON_CMD%" -c "import uvicorn" >nul 2>&1
if not errorlevel 1 goto :check_docx
if /i "%SKIP_DEP_INSTALL%"=="1" (
    echo [ERROR] uvicorn is not installed. Cannot skip dependency installation.
    echo         Remove SKIP_DEP_INSTALL or run: python -m pip install uvicorn
    pause
    exit /b 1
)
echo [ERROR] uvicorn is still unavailable after dependency installation.
echo         Check the Python environment and retry.
pause
exit /b 1

:check_docx
"%PYTHON_CMD%" -c "import docx" >nul 2>&1
if not errorlevel 1 goto :start_server
if /i "%SKIP_DEP_INSTALL%"=="1" (
    echo [ERROR] python-docx is not installed. Cannot skip dependency installation.
    echo         Remove SKIP_DEP_INSTALL or run: python -m pip install python-docx
    pause
    exit /b 1
)
echo [INFO] Installing DOCX export dependency...
"%PYTHON_CMD%" -m pip install --quiet "python-docx>=1.1.0"
if errorlevel 1 (
    echo [ERROR] python-docx installation failed. Server not started.
    pause
    exit /b 1
)
echo [INFO] DOCX export dependency is ready.

rem ---- 5. Start FastAPI ----
:start_server
echo.
echo [INFO] Starting FastAPI...
echo        API: http://127.0.0.1:%PORT%
echo        Docs: http://127.0.0.1:%PORT%/docs
echo        Stop: Ctrl+C
echo ========================================
echo.

"%PYTHON_CMD%" -m uvicorn app.main:app --host 0.0.0.0 --port %PORT% --reload
set "EXIT_CODE=%ERRORLEVEL%"
pause
exit /b %EXIT_CODE%
