param (
    [Parameter(Mandatory=$false)]
    [string]$Phase
)

$ErrorActionPreference = "Stop"

$validPhases = @("00", "01", "02", "03", "04", "05", "06", "07", "08", "09", "10")

if ($PSBoundParameters.ContainsKey("Phase")) {
    $normalizedPhase = $Phase.PadLeft(2, '0')
    if ($normalizedPhase -notin $validPhases) {
        Write-Error "Invalid phase specified: '$Phase'. Valid phases are: $($validPhases -join ', ')"
        exit 1
    }
    $targetPhase = $normalizedPhase
} else {
    $targetPhase = "10"  # Full release gate
}

Write-Host "=== QueryLens Verification Gate: Phase $targetPhase ===" -ForegroundColor Cyan

function Run-Step([string]$name, [scriptblock]$command) {
    Write-Host "==> Checking: $name"
    $tempDir = [System.IO.Path]::GetTempPath()
    $logFile = Join-Path $tempDir "verify_$([System.Guid]::NewGuid().ToString()).log"
    
    try {
        & $command *>&1 | Out-File -FilePath $logFile -Encoding utf8
        $code = $LASTEXITCODE
    } catch {
        $code = 1
        $_ | Out-File -FilePath $logFile -Append -Encoding utf8
    }

    if ($code -ne 0) {
        Write-Host "FAILED: $name (Exit: $code)" -ForegroundColor Red
        Get-Content $logFile -Tail 25 | ForEach-Object { Write-Host $_ }
        Write-Host "Log: $logFile" -ForegroundColor Yellow
        exit $code
    } else {
        Write-Host "PASSED: $name" -ForegroundColor Green
        Remove-Item $logFile -Force -ErrorAction SilentlyContinue
    }
}

# Prerequisites check
Run-Step "Python Environment" {
    if (-not (Test-Path ".venv/bin/python")) {
        throw "Missing .venv/bin/python. Run bootstrap first."
    }
    & .venv/bin/python --version
}

Run-Step "Node Environment" {
    & node -v
    & npm -v
}

# Phase 00 Gates
Run-Step "Phase 00 Unit & Integration Tests" {
    & .venv/bin/pytest apps/api/tests/unit/test_phase_00_01.py apps/api/tests/integration/test_phase_00_02.py -v
}

Run-Step "Phase 00 Web Component Smoke Tests" {
    & npm run test --workspace=apps/web -- src/App.test.tsx
}

if ($targetPhase -ge "01") {
    Run-Step "Phase 01 Migrations & Auth Tests" {
        & .venv/bin/pytest apps/api/tests/unit/test_auth.py apps/api/tests/integration/test_migrations.py apps/api/tests/integration/test_ownership.py -v
    }
}

if ($targetPhase -ge "02") {
    Run-Step "Phase 02 Connection & Encryption Tests" {
        & .venv/bin/pytest apps/api/tests/unit/test_connections.py apps/api/tests/integration/test_adapters.py -v
    }
}

if ($targetPhase -ge "03") {
    Run-Step "Phase 03 Schema Reflection & Catalog Tests" {
        & .venv/bin/pytest apps/api/tests/unit/test_schema.py apps/api/tests/integration/test_schema_reflection.py -v
    }
}

if ($targetPhase -ge "04") {
    Run-Step "Phase 04 AST Policy & Execution Tests" {
        & .venv/bin/pytest apps/api/tests/unit/test_ast_policy.py apps/api/tests/integration/test_execution.py apps/api/tests/security/test_sql_regressions.py -v
    }
}

if ($targetPhase -ge "05") {
    Run-Step "Phase 05 Pipeline & LLM Provider Tests" {
        & .venv/bin/pytest apps/api/tests/unit/test_pipeline.py apps/api/tests/integration/test_vertical_slice.py -v
    }
}

if ($targetPhase -ge "06") {
    Run-Step "Phase 06 Metrics DSL & Few-Shot Tests" {
        & .venv/bin/pytest apps/api/tests/unit/test_metrics.py apps/api/tests/integration/test_retrieval.py -v
    }
}

if ($targetPhase -ge "07") {
    Run-Step "Phase 07 Error Classification & Repair Tests" {
        & .venv/bin/pytest apps/api/tests/unit/test_repair.py apps/api/tests/integration/test_cancellation.py -v
    }
}

if ($targetPhase -ge "08") {
    Run-Step "Phase 08 History & CSV Export Tests" {
        & .venv/bin/pytest apps/api/tests/unit/test_csv_export.py apps/api/tests/integration/test_history.py -v
    }
}

if ($targetPhase -ge "09") {
    Run-Step "Phase 09 Golden Benchmark Tests" {
        & .venv/bin/pytest apps/api/tests/evaluation/test_comparison.py apps/api/tests/evaluation/test_benchmark.py -v
    }
}

if ($targetPhase -ge "10") {
    Run-Step "Phase 10 Release & Hardening Gates" {
        & .venv/bin/pytest apps/api/tests/security/test_profiles.py apps/api/tests/integration/test_load_budgets.py -v
    }

    Run-Step "Everyday Analytics Contracts & Acceptance Tests" {
        & .venv/bin/python scripts/export_schema.py --check
        & .venv/bin/pytest apps/api/tests/unit/test_analytics_contracts.py apps/api/tests/integration/test_everyday_analytics_e2e.py -v
        & npm run test --workspace=apps/web -- src/__tests__/analytics_contracts.test.ts
    }
}

Write-Host "=== VERIFICATION GATE PASSED FOR PHASE $targetPhase ===" -ForegroundColor Green
exit 0
