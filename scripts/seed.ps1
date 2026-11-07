# QueryLens Fixture Seeding Script

$ErrorActionPreference = "Stop"

Write-Host "Seeding database fixtures..." -ForegroundColor Cyan
& .venv/bin/python -m querylens.admin seed-fixtures
