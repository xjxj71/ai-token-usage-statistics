@echo off
setlocal enabledelayedexpansion

set "PROJECT_DIR=%~dp0"
set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"

echo.
echo  ==========================================
echo   AI Token Statistics - Launcher
echo  ==========================================
echo.

:: --- Check Python ---
echo  [1/5] Checking Python ...
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo  [ERROR] Python not found, please install Python 3.11+
    pause
    exit /b 1
)
for /f "tokens=*" %%v in ('python --version 2^>^&1') do echo         %%v

:: --- Check Node.js ---
echo  [2/5] Checking Node.js ...
where node >nul 2>&1
if %errorlevel% neq 0 (
    echo  [ERROR] Node.js not found, please install Node.js 18+
    pause
    exit /b 1
)
for /f "tokens=*" %%v in ('node --version 2^>^&1') do echo         %%v

:: --- Backend venv ---
echo  [3/5] Preparing backend ...
set "VENV_DIR=%PROJECT_DIR%\.venv-win"

if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo         Creating venv ...
    python -m venv "%VENV_DIR%"
    if %errorlevel% neq 0 (
        echo  [ERROR] Failed to create venv
        pause
        exit /b 1
    )
    echo         Done
) else (
    echo         Venv exists, skipping
)

echo         Upgrading pip ...
"%VENV_DIR%\Scripts\python.exe" -m pip install --upgrade pip -i https://pypi.org/simple/ --quiet 2>nul

echo         Installing setuptools ...
"%VENV_DIR%\Scripts\pip.exe" install setuptools -i https://pypi.org/simple/ --quiet 2>nul

echo         Installing backend deps ...
"%VENV_DIR%\Scripts\pip.exe" install -e "%PROJECT_DIR%" -i https://pypi.org/simple/
if %errorlevel% neq 0 (
    echo  [ERROR] Failed to install backend deps
    pause
    exit /b 1
)

if not exist "%PROJECT_DIR%\data" mkdir "%PROJECT_DIR%\data"

:: --- Frontend deps ---
echo  [4/5] Preparing frontend ...
:: Windows node_modules marker - separate from WSL's
set "FE_NM=%PROJECT_DIR%\frontend\node_modules\.package-lock.json"
set "FE_WIN_MARKER=%PROJECT_DIR%\frontend\node_modules\.windows-installed"

if not exist "%FE_WIN_MARKER%" (
    echo         Installing npm deps for Windows ...
    cd /d "%PROJECT_DIR%\frontend"
    call npm install
    if %errorlevel% neq 0 (
        echo  [ERROR] npm install failed
        cd /d "%PROJECT_DIR%"
        pause
        exit /b 1
    )
    echo. > "%FE_WIN_MARKER%"
    cd /d "%PROJECT_DIR%"
) else (
    echo         node_modules ready, skipping
)

:: --- Start services ---
echo  [5/5] Starting services ...
echo.

:: Kill old processes on target ports
for /f "tokens=5" %%p in ('netstat -ano 2^>nul ^| findstr ":8000.*LISTENING"') do (
    echo         Killing old backend PID=%%p
    taskkill /pid %%p /f >nul 2>&1
)
for /f "tokens=5" %%p in ('netstat -ano 2^>nul ^| findstr ":5173.*LISTENING"') do (
    echo         Killing old frontend PID=%%p
    taskkill /pid %%p /f >nul 2>&1
)

:: Write temp launcher scripts to avoid quoting issues
set "TMP_BAT=%TEMP%\token-stat-backend.bat"
echo @echo off > "%TMP_BAT%"
echo cd /d "%PROJECT_DIR%" >> "%TMP_BAT%"
echo "%VENV_DIR%\Scripts\python.exe" -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload >> "%TMP_BAT%"
echo pause >> "%TMP_BAT%"

set "TMP_BAT_FE=%TEMP%\token-stat-frontend.bat"
echo @echo off > "%TMP_BAT_FE%"
echo cd /d "%PROJECT_DIR%\frontend" >> "%TMP_BAT_FE%"
echo node node_modules\vite\bin\vite.js --host 0.0.0.0 --port 5173 >> "%TMP_BAT_FE%"
echo pause >> "%TMP_BAT_FE%"

:: Start backend in new window
echo         Starting backend (FastAPI :8000) ...
start "TokenStat-Backend" /min "%TMP_BAT%"

:: Wait for backend
echo         Waiting for backend ...
set "READY=0"
for /l %%i in (1,1,30) do (
    if !READY! equ 0 (
        curl -s http://127.0.0.1:8000/api/models >nul 2>&1
        if !errorlevel! equ 0 (
            set "READY=1"
            echo         Backend ready
        ) else (
            timeout /t 1 /nobreak >nul
        )
    )
)
if %READY% equ 0 (
    echo         [WARN] Backend may not be ready yet
)

:: Start frontend in new window
echo         Starting frontend (Vite :5173) ...
start "TokenStat-Frontend" /min "%TMP_BAT_FE%"

:: Open browser
timeout /t 3 /nobreak >nul
echo         Opening browser ...
start http://127.0.0.1:5173

echo.
echo  ------------------------------------------
echo   Backend:  http://127.0.0.1:8000
echo   Frontend: http://127.0.0.1:5173
echo.
echo   Close this window won't stop services
echo   Run stop.bat to stop all services
echo  ------------------------------------------
echo.
pause
