$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$processFile = Join-Path $projectRoot '.local/processes.json'
if (-not (Test-Path -LiteralPath $processFile)) { Write-Host 'No recorded project processes.'; exit 0 }
$records = Get-Content -LiteralPath $processFile -Raw | ConvertFrom-Json
foreach ($record in $records) {
    $process = Get-Process -Id $record.id -ErrorAction SilentlyContinue
    if ($process -and $process.StartTime.ToUniversalTime() -eq ([datetime]$record.started).ToUniversalTime()) {
        # The Windows venv launcher can own a Python child. Stop only the verified
        # recorded process tree, not unrelated services using the same executable.
        & taskkill.exe /PID $process.Id /T /F | Out-Null
        Write-Host "Stopped $($record.name) ($($record.id))"
    }
}
Remove-Item -LiteralPath $processFile
