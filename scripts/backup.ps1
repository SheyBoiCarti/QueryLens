# QueryLens Metadata Database Backup Script
# Contracts: C04, C11

param (
    [Parameter(Mandatory=$false)]
    [string]$DestinationDir = "backups",

    [Parameter(Mandatory=$false)]
    [string]$DatabaseUrl = $env:METADATA_DATABASE_URL
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $DestinationDir)) {
    New-Item -ItemType Directory -Path $DestinationDir -Force | Out-Null
}

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$backupFile = Join-Path $DestinationDir "querylens_metadata_$timestamp.sql"

Write-Host "Backing up QueryLens metadata to $backupFile..." -ForegroundColor Cyan

& .venv/bin/python -c "
import os
import sys
import sqlalchemy as sa

db_url = '$DatabaseUrl' if '$DatabaseUrl' else os.environ.get('METADATA_DATABASE_URL', 'sqlite:///./metadata.db')
engine = sa.create_engine(db_url)

with open('$backupFile', 'w', encoding='utf-8') as out_f:
    out_f.write('-- QueryLens Metadata Backup Timestamp: $timestamp\n')
    with engine.connect() as conn:
        # Export tables metadata
        meta = sa.MetaData()
        meta.reflect(bind=engine)
        for table_name in meta.tables:
            out_f.write(f'-- Table: {table_name}\n')
            res = conn.execute(sa.text(f'SELECT * FROM {table_name}'))
            for r in res.fetchall():
                out_f.write(f'-- Row: {dict(r._mapping)}\n')

print('Backup completed successfully.')
"

if ($LASTEXITCODE -ne 0) {
    Write-Error "Backup failed with exit code $LASTEXITCODE"
    exit 1
}

Write-Host "Backup completed: $backupFile" -ForegroundColor Green
exit 0
