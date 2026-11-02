param([switch]$Install, [switch]$Initialize, [string]$Username = 'admin')
$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$backendDir = Join-Path $projectRoot 'backend'
$frontendDir = Join-Path $projectRoot 'frontend'
$pythonBin = Join-Path $projectRoot '.venv/Scripts/python.exe'
$runtimeDir = Join-Path $projectRoot '.local'
New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null
if ($Install) {
    if (-not (Test-Path -LiteralPath $pythonBin)) {
        & py -3 -m venv (Join-Path $projectRoot '.venv')
        if ($LASTEXITCODE -ne 0) { throw 'Python 3.11+ is required.' }
    }
    & $pythonBin -m pip install -r (Join-Path $backendDir 'requirements.txt') -c (Join-Path $backendDir 'requirements.lock.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Backend dependencies failed.' }
    Push-Location $frontendDir
    try { npm ci; if ($LASTEXITCODE -ne 0) { throw 'Frontend dependencies failed.' } } finally { Pop-Location }
}
if (-not (Test-Path -LiteralPath $pythonBin)) { throw 'Run with -Install first.' }
Push-Location $backendDir
try {
    & $pythonBin -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) { throw 'Database migration failed.' }
    if ($Initialize) {
        & $pythonBin -m app.cli create-admin --username $Username
        if ($LASTEXITCODE -ne 0) { throw 'Administrator initialization failed.' }
    }
} finally { Pop-Location }
$processes = @()
foreach ($port in @(8000, 5173)) {
    if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) { throw "Port $port is occupied. Stop the existing project instance before starting another." }
}
$api = Start-Process -FilePath $pythonBin -ArgumentList @('-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8000','--no-access-log') -WorkingDirectory $backendDir -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runtimeDir 'api.stdout.log') -RedirectStandardError (Join-Path $runtimeDir 'api.stderr.log')
$processes += @{id=$api.Id; started=$api.StartTime.ToUniversalTime().ToString('o'); name='API'}
$nodeBin = (Get-Command node).Source
$viteEntry = Join-Path $frontendDir 'node_modules/vite/bin/vite.js'
$web = Start-Process -FilePath $nodeBin -ArgumentList @(('"' + $viteEntry + '"'),'--host','127.0.0.1','--port','5173','--strictPort') -WorkingDirectory $frontendDir -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runtimeDir 'frontend.stdout.log') -RedirectStandardError (Join-Path $runtimeDir 'frontend.stderr.log')
$processes += @{id=$web.Id; started=$web.StartTime.ToUniversalTime().ToString('o'); name='Frontend'}
$processes | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $runtimeDir 'processes.json') -Encoding utf8
$healthy = $false
for ($attempt = 0; $attempt -lt 30; $attempt++) {
    try {
        $apiCheck = Invoke-WebRequest 'http://127.0.0.1:8000/api/health' -UseBasicParsing -TimeoutSec 2
        $webCheck = Invoke-WebRequest 'http://127.0.0.1:5173' -UseBasicParsing -TimeoutSec 2
        if ($apiCheck.StatusCode -eq 200 -and $webCheck.StatusCode -eq 200) { $healthy = $true; break }
    } catch { Start-Sleep -Seconds 1 }
}
if (-not $healthy) { throw 'Startup failed. See .local/*.log; use deploy/stop-local.ps1 to stop these processes.' }
Write-Host 'ClassBridge is running at http://127.0.0.1:5173'
Write-Host 'OpenAPI: http://127.0.0.1:8000/api/docs'
Write-Host 'Demo mode never invokes paid APIs. Stop: ./deploy/stop-local.ps1'
