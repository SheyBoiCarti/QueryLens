@echo off
setlocal enabledelayedexpansion
title QueryLens - Starting...

echo ===================================================
echo               Starting QueryLens...
echo ===================================================
echo.

cd /d "%~dp0"

:: 1. Start Backend API Server
echo [1/2] Starting Backend API Server (http://127.0.0.1:8000)...
start "QueryLens API" cmd /k ""%~dp0.venv\Scripts\python.exe" -m uvicorn querylens.main:app --host 127.0.0.1 --port 8000"

:: Brief pause to let backend initialize
%SystemRoot%\System32\ping.exe -n 3 127.0.0.1 >nul

:: 2. Start Frontend Web Server
echo [2/2] Starting Frontend Vite Server (http://localhost:5173)...
start "QueryLens Web" cmd /k "cd /d "%~dp0apps\web" && npm run dev"

:: Wait and open browser automatically
%SystemRoot%\System32\ping.exe -n 4 127.0.0.1 >nul
echo.
echo Launching QueryLens in browser...
start http://localhost:5173

echo.
echo ===================================================
echo   QueryLens services launched successfully!
echo   - Web UI:  http://localhost:5173
echo   - API:     http://127.0.0.1:8000
echo.
echo   Run stop.bat anytime to shut down all services.
echo ===================================================
%SystemRoot%\System32\ping.exe -n 4 127.0.0.1 >nul
