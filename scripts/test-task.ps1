param (
    [Parameter(Mandatory=$true)]
    [string]$TestPath
)

$ErrorActionPreference = "Stop"

$tempDir = [System.IO.Path]::GetTempPath()
$logFile = Join-Path $tempDir "querylens_test_task_$([System.Guid]::NewGuid().ToString()).log"

Write-Host "Running task test: $TestPath"

if ($TestPath.EndsWith(".py")) {
    $pythonCmd = if (Test-Path ".venv/bin/python") { ".venv/bin/python" } else { "python3" }
    $pytestCmd = if (Test-Path ".venv/bin/pytest") { ".venv/bin/pytest" } else { "pytest" }
    
    & $pytestCmd $TestPath -v *>&1 | Out-File -FilePath $logFile -Encoding utf8
    $exitCode = $LASTEXITCODE
} elseif ($TestPath.EndsWith(".ts") -or $TestPath.EndsWith(".tsx")) {
    & npm run test --workspace=apps/web -- $TestPath *>&1 | Out-File -FilePath $logFile -Encoding utf8
    $exitCode = $LASTEXITCODE
} else {
    Write-Error "Unknown test runner for file: $TestPath"
    exit 1
}

if ($exitCode -ne 0) {
    Write-Host "TASK TEST FAILED (Exit Code: $exitCode). Relevant failure log excerpt:" -ForegroundColor Red
    Get-Content $logFile -Tail 30 | ForEach-Object { Write-Host $_ }
    Write-Host "Full log at: $logFile" -ForegroundColor Yellow
    exit $exitCode
} else {
    Write-Host "TASK TEST PASSED: $TestPath" -ForegroundColor Green
    Remove-Item $logFile -Force -ErrorAction SilentlyContinue
    exit 0
}
