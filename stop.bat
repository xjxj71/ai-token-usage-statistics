@echo off
echo.
echo  ==========================================
echo   AI Token Statistics - Stop Services
echo  ==========================================
echo.

set "FOUND=0"

for /f "tokens=5" %%p in ('netstat -ano 2^>nul ^| findstr ":8000.*LISTENING"') do (
    echo  Stopping backend PID=%%p
    taskkill /pid %%p /f >nul 2>&1
    set "FOUND=1"
)

for /f "tokens=5" %%p in ('netstat -ano 2^>nul ^| findstr ":5173.*LISTENING"') do (
    echo  Stopping frontend PID=%%p
    taskkill /pid %%p /f >nul 2>&1
    set "FOUND=1"
)

if %FOUND% equ 0 (
    echo  No running services found
) else (
    echo.
    echo  All services stopped
)
echo.
pause
