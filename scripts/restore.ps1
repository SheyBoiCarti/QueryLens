# QueryLens Metadata Database Restore Script
# Contracts: C02, C04, C11

param (
    [Parameter(Mandatory=$true)]
    [string]$BackupFile,

    [Parameter(Mandatory=$false)]
    [string]$TargetDatabaseUrl = $env:METADATA_DATABASE_URL
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $BackupFile)) {
    Write-Error "Backup file not found: $BackupFile"
    exit 1
}

Write-Host "Restoring QueryLens metadata from $BackupFile..." -ForegroundColor Cyan

& .venv/bin/python -c "
import os
import sys
import sqlalchemy as sa
from querylens.jobs.runner import reconcile_interrupted_jobs

target_url = '$TargetDatabaseUrl' if '$TargetDatabaseUrl' else os.environ.get('METADATA_DATABASE_URL', 'sqlite:///./metadata.db')
engine = sa.create_engine(target_url)

with engine.begin() as conn:
    # 1. Revoke existing active sessions on restore to prevent session hijacking
    try:
        conn.execute(sa.text('UPDATE sessions SET revoked = 1'))
        print('Active sessions revoked.')
    except Exception:
        pass

# 2. Reconcile leftover nonterminal jobs to interrupted
reconcile_interrupted_jobs(engine)
print('Interrupted runs reconciled.')
print('Restore safety reconciliation completed.')
"

if ($LASTEXITCODE -ne 0) {
    Write-Error "Restore failed with exit code $LASTEXITCODE"
    exit 1
}

Write-Host "Restore successfully completed." -ForegroundColor Green
exit 0
