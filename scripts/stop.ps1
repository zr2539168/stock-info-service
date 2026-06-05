param(
    [int]$Port = 8000,
    [switch]$ByPort
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$PidFile = Join-Path $Root "data\service.pid"

$stopped = $false

if (Test-Path $PidFile) {
    $rawPid = (Get-Content $PidFile -Raw).Trim()
    if ($rawPid) {
        try {
            $process = Get-Process -Id ([int]$rawPid) -ErrorAction Stop
            Write-Host "Stopping Stock Info Service. PID: $rawPid"
            Stop-Process -Id $process.Id -Force
            $stopped = $true
        } catch {
            Write-Host "PID file exists, but process $rawPid is not running."
        }
    }
    Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
}

if ($ByPort -and -not $stopped) {
    $listeners = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    foreach ($listener in $listeners) {
        Write-Host "Stopping process $($listener.OwningProcess) listening on port $Port"
        Stop-Process -Id $listener.OwningProcess -Force
        $stopped = $true
    }
}

if ($stopped) {
    Write-Host "Stopped."
} else {
    Write-Host "Stock Info Service was not running."
    Write-Host "If the service is running without a PID file, use: .\scripts\stop.ps1 -ByPort"
}
