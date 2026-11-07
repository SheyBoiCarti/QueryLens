# QueryLens Bootstrap Script

$ErrorActionPreference = "Stop"

Write-Host "Bootstrapping QueryLens repository..." -ForegroundColor Cyan

# 1. Check Python
if (-not (Get-Command python3 -ErrorAction SilentlyContinue)) {
    Write-Error "Python 3 is required."
    exit 1
}

# 2. Virtualenv
if (-not (Test-Path ".venv")) {
    Write-Host "Creating Python virtual environment..."
    & python3 -m venv .venv
}

# 3. Python packages
Write-Host "Installing locked Python dependencies..."
& .venv/bin/pip install --upgrade pip
& .venv/bin/pip install -r apps/api/requirements.lock
& .venv/bin/pip install -e apps/api

# 4. Node packages
Write-Host "Installing locked npm packages..."
& npm ci

Write-Host "QueryLens bootstrap complete!" -ForegroundColor Green
