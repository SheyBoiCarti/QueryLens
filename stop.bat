@echo off
setlocal enabledelayedexpansion
title QueryLens - Stopping...

echo ===================================================
echo               Stopping QueryLens...
echo ===================================================
echo.

:: 1. Stop processes listening on port 8000 (Backend API)
echo Checking port 8000 (API Server)...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000" ^| findstr "LISTENING"') do (
    echo Terminating API process PID %%a...
    taskkill /F /PID %%a >nul 2>&1
)

:: 2. Stop processes listening on port 5173 (Frontend Web Server)
echo Checking port 5173 (Frontend Web Server)...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5173" ^| findstr "LISTENING"') do (
    echo Terminating Web process PID %%a...
    taskkill /F /PID %%a >nul 2>&1
)

:: 3. Close leftover cmd windows by window title if still open
taskkill /FI "WINDOWTITLE eq QueryLens API*" /T /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq QueryLens Web*" /T /F >nul 2>&1

echo.
echo ===================================================
echo   QueryLens services stopped successfully.
echo ===================================================
%SystemRoot%\System32\ping.exe -n 3 127.0.0.1 >nul
