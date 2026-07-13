@echo off
setlocal enabledelayedexpansion
chcp 65001 > nul
title CallCenterAI - Launcher

REM ============================================================
REM  CallCenterAI - One-click launcher
REM  Starts: Backend (FastAPI/uvicorn :8000) + Frontend (Vite :5173)
REM  Then opens browser at http://localhost:5173
REM ============================================================

REM --- Resolve project root (folder of this .bat) ---
set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"

set "BACKEND_DIR=%ROOT%\backend"
set "FRONTEND_DIR=%ROOT%"
set "VENV_PYTHON=%BACKEND_DIR%\.venv\Scripts\python.exe"
set "VENV_UVICORN=%BACKEND_DIR%\.venv\Scripts\uvicorn.exe"
set "BE_PORT=8000"
set "FE_PORT=5173"
set "FE_URL=http://localhost:%FE_PORT%"

echo.
echo ============================================================
echo   CallCenterAI Launcher
echo ============================================================
echo   Project root : %ROOT%
echo   Backend dir  : %BACKEND_DIR%
echo   Backend URL  : http://localhost:%BE_PORT%/api/health
echo   Frontend URL : %FE_URL%
echo ============================================================
echo.

REM --- Pre-flight checks ---
if not exist "%VENV_PYTHON%" (
    echo [ERROR] Backend venv python not found:
    echo   %VENV_PYTHON%
    echo   Create it first:  cd backend ^&^& python -m venv .venv ^&^& .venv\Scripts\pip install -r requirements.txt
    pause
    exit /b 1
)

if not exist "%VENV_UVICORN%" (
    echo [ERROR] uvicorn not installed in backend venv:
    echo   %VENV_UVICORN%
    echo   Install it:  cd backend ^&^& .venv\Scripts\pip install -r requirements.txt
    pause
    exit /b 1
)

if not exist "%FRONTEND_DIR%\node_modules" (
    echo [ERROR] Frontend node_modules not found. Run:  npm install
    pause
    exit /b 1
)

REM --- Check if backend port is already in use ---
set "BE_ALREADY=0"
netstat -ano | findstr ":%BE_PORT% " | findstr "LISTENING" > nul 2>&1 && set "BE_ALREADY=1"

REM --- Check if frontend port is already in use ---
set "FE_ALREADY=0"
netstat -ano | findstr ":%FE_PORT% " | findstr "LISTENING" > nul 2>&1 && set "FE_ALREADY=1"

REM --- Start Backend (if not already running) ---
if "!BE_ALREADY!"=="1" goto BE_SKIP
echo [1/3] Starting Backend (uvicorn :%BE_PORT%) in new window...
start "CallCenterAI - Backend" cmd /k "cd /d "%BACKEND_DIR%" && "%VENV_UVICORN%" app.main:app --host 127.0.0.1 --port %BE_PORT% --reload"
goto BE_DONE
:BE_SKIP
echo [1/3] Backend already running on port %BE_PORT% - skipping.
:BE_DONE

REM --- Start Frontend (if not already running) ---
if "!FE_ALREADY!"=="1" goto FE_SKIP
echo [2/3] Starting Frontend (vite :%FE_PORT%) in new window...
start "CallCenterAI - Frontend" cmd /k "cd /d "%FRONTEND_DIR%" && npm run dev"
goto FE_DONE
:FE_SKIP
echo [2/3] Frontend already running on port %FE_PORT% - skipping.
:FE_DONE

REM --- Wait for backend healthcheck before opening browser ---
if "!BE_ALREADY!"=="1" goto BE_READY_SKIP
echo [3/3] Waiting for backend to be ready...
set /a WAIT_SEC=0
:WAIT_BE
timeout /t 1 /nobreak > nul
set /a WAIT_SEC+=1
powershell -NoProfile -Command "try { $r = Invoke-WebRequest -Uri 'http://localhost:%BE_PORT%/api/health' -UseBasicParsing -TimeoutSec 2; if ($r.StatusCode -eq 200) { exit 0 } else { exit 1 } } catch { exit 1 }" > nul 2>&1
if not errorlevel 1 goto BE_READY
if !WAIT_SEC! geq 30 goto BE_TIMEOUT
goto WAIT_BE
:BE_READY
echo       Backend ready after !WAIT_SEC!s.
goto WAIT_FE_START
:BE_TIMEOUT
echo       [WARN] Backend not ready after 30s - opening browser anyway.
goto WAIT_FE_START
:BE_READY_SKIP
echo [3/3] Backend already running - skipping wait.

REM --- Wait briefly for Vite to be ready ---
:WAIT_FE_START
if "!FE_ALREADY!"=="1" goto FE_READY_SKIP
echo       Waiting for Vite dev server...
set /a WAIT_SEC=0
:WAIT_FE
timeout /t 1 /nobreak > nul
set /a WAIT_SEC+=1
powershell -NoProfile -Command "try { $r = Invoke-WebRequest -Uri '%FE_URL%' -UseBasicParsing -TimeoutSec 2; if ($r.StatusCode -eq 200) { exit 0 } else { exit 1 } } catch { exit 1 }" > nul 2>&1
if not errorlevel 1 goto FE_READY
if !WAIT_SEC! geq 20 goto FE_TIMEOUT
goto WAIT_FE
:FE_READY
echo       Vite ready after !WAIT_SEC!s.
goto OPEN_BROWSER
:FE_TIMEOUT
echo       [WARN] Vite not ready after 20s - opening browser anyway.
goto OPEN_BROWSER
:FE_READY_SKIP
echo       Frontend already running.

:OPEN_BROWSER
echo.
echo ============================================================
echo   Opening browser: %FE_URL%
echo ============================================================
echo.
echo   Backend window  : "CallCenterAI - Backend"
echo   Frontend window : "CallCenterAI - Frontend"
echo   Close those windows to stop the servers.
echo.
start "" "%FE_URL%"

endlocal
