# QueryLens Application Smoke Test Script
# Contracts: C01, C02, C08

param (
    [Parameter(Mandatory=$false)]
    [string]$BaseUrl = "http://127.0.0.1:8000"
)

$ErrorActionPreference = "Stop"

Write-Host "Running smoke tests against $BaseUrl..." -ForegroundColor Cyan

& .venv/bin/python -c "
import sys
import httpx

base_url = '$BaseUrl'.rstrip('/')
try:
    with httpx.Client(base_url=base_url, timeout=5.0) as client:
        # 1. Health check
        r = client.get('/health')
        assert r.status_code == 200, f'Health check failed: {r.status_code}'
        assert r.json().get('status') == 'ok', 'Health status is not ok'
        print('PASSED: /health endpoint')

        # 2. OpenAPI specification
        r = client.get('/openapi.json')
        assert r.status_code == 200, f'OpenAPI spec failed: {r.status_code}'
        print('PASSED: /openapi.json endpoint')

        # 3. Shared workspace access
        r = client.get('/api/v1/connections')
        assert r.status_code == 200, f'Connections failed: {r.status_code}'
        print('PASSED: Shared workspace access')

    print('All smoke checks passed!')
except Exception as e:
    print(f'Smoke test error: {e}')
    sys.exit(1)
"

if ($LASTEXITCODE -ne 0) {
    Write-Error "Smoke tests failed."
    exit 1
}

Write-Host "All application smoke checks succeeded." -ForegroundColor Green
exit 0
