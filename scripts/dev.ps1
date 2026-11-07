# QueryLens Dev Server Launcher

$ErrorActionPreference = "Stop"

Write-Host "Starting QueryLens API development server on http://127.0.0.1:8000..." -ForegroundColor Cyan
& .venv/bin/uvicorn querylens.main:app --host 127.0.0.1 --port 8000 --reload
