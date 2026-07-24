param(
    [switch]$NoDocker,
    [switch]$Restart
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$WebDir = Join-Path $Root "apps\web"
$BackendLog = Join-Path $Root "backend.log"
$FrontendLog = Join-Path $Root "frontend.log"
$BackendPidFile = Join-Path $Root ".backend.pid"
$FrontendPidFile = Join-Path $Root ".frontend.pid"

function Write-Step($Message) {
    Write-Host "[run-all] $Message" -ForegroundColor Cyan
}

function Write-Ok($Message) {
    Write-Host "[run-all] $Message" -ForegroundColor Green
}

function Write-Warn($Message) {
    Write-Host "[run-all] $Message" -ForegroundColor Yellow
}

function Test-Port($Port) {
    try {
        $client = New-Object Net.Sockets.TcpClient
        $iar = $client.BeginConnect("127.0.0.1", $Port, $null, $null)
        $connected = $iar.AsyncWaitHandle.WaitOne(250, $false)
        if ($connected) {
            $client.EndConnect($iar)
        }
        $client.Close()
        return $connected
    } catch {
        return $false
    }
}

function Stop-TrackedProcess($PidFile, $Name) {
    if (-not (Test-Path $PidFile)) {
        return
    }

    $rawPid = (Get-Content $PidFile -ErrorAction SilentlyContinue | Select-Object -First 1)
    if (-not $rawPid) {
        Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
        return
    }

    $proc = Get-Process -Id ([int]$rawPid) -ErrorAction SilentlyContinue
    if ($proc) {
        Write-Step "Stopping previous $Name process (PID $rawPid)..."
        taskkill.exe /PID $proc.Id /T /F | Out-Null
    }
    Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
}

function Quote-PS($Value) {
    return "'" + ($Value -replace "'", "''") + "'"
}

function Wait-Http($Url, $Name, $TimeoutSeconds) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            Invoke-RestMethod -Uri $Url -Method Get -TimeoutSec 2 | Out-Null
            Write-Ok "$Name is ready."
            return $true
        } catch {
            Start-Sleep -Seconds 1
        }
    }
    return $false
}

function Start-DevWindow($Name, $Command, $WorkingDirectory, $LogPath, $PidFile) {
    if (Test-Path $LogPath) {
        Remove-Item $LogPath -Force
    }

    $proc = Start-Process `
        -FilePath "powershell.exe" `
        -ArgumentList "-NoProfile -ExecutionPolicy Bypass -NoExit -Command ""$Command""" `
        -WorkingDirectory $WorkingDirectory `
        -WindowStyle Normal `
        -PassThru

    Set-Content -Path $PidFile -Value $proc.Id -Encoding ascii
    Write-Ok "$Name started (PID $($proc.Id), log: $LogPath)."
}

Set-Location $Root

if ($Restart) {
    Stop-TrackedProcess $BackendPidFile "backend"
    Stop-TrackedProcess $FrontendPidFile "frontend"
}

if (-not $NoDocker) {
    Write-Step "Starting Docker services (Postgres + Qdrant)..."
    docker compose up -d

    if (-not (Wait-Http "http://127.0.0.1:6333/healthz" "Qdrant" 45)) {
        throw "Qdrant did not become ready on http://127.0.0.1:6333. Check Docker Desktop and run: docker compose logs qdrant"
    }
}

if (-not (Test-Path (Join-Path $Root "venv\Scripts\python.exe"))) {
    throw "Python venv was not found at venv\Scripts\python.exe. Create/restore the virtualenv first."
}

if (-not (Test-Path (Join-Path $WebDir "node_modules"))) {
    throw "Frontend dependencies were not found at apps\web\node_modules. Run: cd apps\web; npm install"
}

if (-not (Test-Port 5000)) {
    Write-Step "Starting FastAPI backend on http://127.0.0.1:5000..."
    $pythonPath = Join-Path $Root "venv\Scripts\python.exe"
    $backendCommand = "& $(Quote-PS $pythonPath) serve.py 2>&1 | Tee-Object -FilePath $(Quote-PS $BackendLog)"
    Start-DevWindow `
        -Name "Backend" `
        -Command $backendCommand `
        -WorkingDirectory $Root `
        -LogPath $BackendLog `
        -PidFile $BackendPidFile
} else {
    Write-Warn "Port 5000 is already in use. Backend start skipped."
}

if (-not (Wait-Http "http://127.0.0.1:5000/api/health" "Backend" 60)) {
    Write-Host ""
    Write-Warn "Backend did not become ready. Last backend log lines:"
    if (Test-Path $BackendLog) {
        Get-Content $BackendLog -Tail 80
    }
    Stop-TrackedProcess $BackendPidFile "backend"
    throw "Backend is not ready on http://127.0.0.1:5000."
}

if (-not (Test-Port 3000)) {
    Write-Step "Starting Next.js frontend on http://127.0.0.1:3000..."
    $frontendCommand = "& npm.cmd run dev 2>&1 | Tee-Object -FilePath $(Quote-PS $FrontendLog)"
    Start-DevWindow `
        -Name "Frontend" `
        -Command $frontendCommand `
        -WorkingDirectory $WebDir `
        -LogPath $FrontendLog `
        -PidFile $FrontendPidFile
} else {
    Write-Warn "Port 3000 is already in use. Frontend start skipped."
}

if (-not (Wait-Http "http://127.0.0.1:3000" "Frontend" 60)) {
    Write-Host ""
    Write-Warn "Frontend did not become ready. Last frontend log lines:"
    if (Test-Path $FrontendLog) {
        Get-Content $FrontendLog -Tail 80
    }
    Stop-TrackedProcess $FrontendPidFile "frontend"
    throw "Frontend is not ready on http://127.0.0.1:3000."
}

Write-Host ""
Write-Ok "All services are up."
Write-Host "Frontend: http://127.0.0.1:3000"
Write-Host "Backend:  http://127.0.0.1:5000/api/health"
Write-Host "Qdrant:   http://127.0.0.1:6333/dashboard"
Write-Host ""
Write-Host "Logs:"
Write-Host "  Backend:  Get-Content .\backend.log -Wait"
Write-Host "  Frontend: Get-Content .\frontend.log -Wait"
Write-Host ""
Write-Host "Stop:"
Write-Host "  .\stop-all.cmd"
