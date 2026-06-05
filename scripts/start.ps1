param(
    [string]$HostName = "127.0.0.1",
    [int]$Port = 8000,
    [switch]$NoInstall
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$VenvDir = Join-Path $Root ".venv"
$Python = Join-Path $VenvDir "Scripts\python.exe"
$DataDir = Join-Path $Root "data"
$LogDir = Join-Path $Root "logs"
$PidFile = Join-Path $DataDir "service.pid"
$OutLog = Join-Path $LogDir "service.out.log"
$ErrLog = Join-Path $LogDir "service.err.log"

function Test-RunningPid {
    param([string]$Path)
    if (-not (Test-Path $Path)) {
        return $false
    }
    $rawPid = (Get-Content $Path -Raw).Trim()
    if (-not $rawPid) {
        return $false
    }
    try {
        $process = Get-Process -Id ([int]$rawPid) -ErrorAction Stop
        return $null -ne $process
    } catch {
        return $false
    }
}

New-Item -ItemType Directory -Force -Path $DataDir, $LogDir | Out-Null

if (Test-RunningPid $PidFile) {
    $runningPid = (Get-Content $PidFile -Raw).Trim()
    Write-Host "Stock Info Service is already running. PID: $runningPid"
    Write-Host "URL: http://${HostName}:$Port"
    exit 0
}

$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($listener) {
    Write-Host "Port $Port is already in use by process $($listener.OwningProcess)."
    Write-Host "Stop that process or start with another port: .\scripts\start.ps1 -Port 8001"
    exit 1
}

if (-not (Test-Path $Python)) {
    Write-Host "Creating virtual environment..."
    try {
        & py -3.12 -m venv $VenvDir
    } catch {
        & python -m venv $VenvDir
    }
}

if (-not $NoInstall) {
    Write-Host "Installing/updating dependencies..."
    & $Python -m pip install -e $Root
}

Write-Host "Starting Stock Info Service..."
$args = @("-m", "uvicorn", "app.main:app", "--host", $HostName, "--port", "$Port")
$process = Start-Process `
    -FilePath $Python `
    -ArgumentList $args `
    -WorkingDirectory $Root `
    -WindowStyle Hidden `
    -RedirectStandardOutput $OutLog `
    -RedirectStandardError $ErrLog `
    -PassThru

Set-Content -Path $PidFile -Value $process.Id
Write-Host "Started. PID: $($process.Id)"
Write-Host "URL: http://${HostName}:$Port"
Write-Host "Logs:"
Write-Host "  $OutLog"
Write-Host "  $ErrLog"
