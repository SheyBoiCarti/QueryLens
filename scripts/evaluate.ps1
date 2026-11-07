# QueryLens Evaluation CLI Script
# Contracts: C01, C10

param (
    [Parameter(Mandatory=$false)]
    [string]$Engine = "postgres",

    [Parameter(Mandatory=$false)]
    [string]$Provider = "fake",

    [Parameter(Mandatory=$false)]
    [string]$Cases = "benchmarks/cases/heldout.json",

    [Parameter(Mandatory=$false)]
    [string]$Variant = "A",

    [Parameter(Mandatory=$false)]
    [string]$OutputDir = "benchmarks/results"
)

$ErrorActionPreference = "Stop"

Write-Host "Running QueryLens Evaluation..." -ForegroundColor Cyan
Write-Host "Engine: $Engine | Provider: $Provider | Cases: $Cases | Variant: $Variant"

& .venv/bin/python -c "
import sys
from querylens.evaluation.runner import evaluate
report, code = evaluate(
    engine='$Engine',
    provider='$Provider',
    case_set='$Cases',
    output_dir='$OutputDir',
    variant='$Variant',
)
print('Evaluation completed with exit code:', code)
sys.exit(code)
"

exit $LASTEXITCODE
