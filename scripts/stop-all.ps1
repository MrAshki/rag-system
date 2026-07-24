$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$BackendPidFile = Join-Path $Root ".backend.pid"
$FrontendPidFile = Join-Path $Root ".frontend.pid"

function Stop-TrackedProcess($PidFile, $Name) {
    if (-not (Test-Path $PidFile)) {
        Write-Host "[stop-all] No tracked $Name process."
        return
    }

    $rawPid = (Get-Content $PidFile -ErrorAction SilentlyContinue | Select-Object -First 1)
    if ($rawPid) {
        $proc = Get-Process -Id ([int]$rawPid) -ErrorAction SilentlyContinue
        if ($proc) {
            Write-Host "[stop-all] Stopping $Name (PID $rawPid)..."
            taskkill.exe /PID $proc.Id /T /F | Out-Null
        } else {
            Write-Host "[stop-all] Tracked $Name process is not running."
        }
    }

    Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
}

Stop-TrackedProcess $BackendPidFile "backend"
Stop-TrackedProcess $FrontendPidFile "frontend"

Write-Host "[stop-all] App processes stopped. Docker services are still running."
Write-Host "[stop-all] To stop Postgres + Qdrant too: docker compose down"
