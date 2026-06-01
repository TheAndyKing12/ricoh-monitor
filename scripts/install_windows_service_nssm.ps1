param(
    [string]$InstallPath = "C:\ricoh-monitor",
    [string]$ServiceName = "RicohMonitor",
    [string]$NssmExe = "C:\nssm\nssm.exe"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $NssmExe)) {
    throw "NSSM not found at $NssmExe. Download NSSM or pass -NssmExe with the correct path."
}

$python = Join-Path $InstallPath "backend\venv\Scripts\python.exe"
$backend = Join-Path $InstallPath "backend"

if (-not (Test-Path $python)) {
    throw "Python venv not found. Run scripts\windows_prepare_server.ps1 first."
}

& $NssmExe install $ServiceName $python "-m uvicorn app.main:app --host 0.0.0.0 --port 8000"
& $NssmExe set $ServiceName AppDirectory $backend
& $NssmExe set $ServiceName DisplayName "Ricoh Monitor"
& $NssmExe set $ServiceName Description "Ricoh Monitor FastAPI backend and static frontend"
& $NssmExe set $ServiceName Start SERVICE_AUTO_START
& $NssmExe set $ServiceName AppStdout (Join-Path $InstallPath "logs\ricoh-monitor.out.log")
& $NssmExe set $ServiceName AppStderr (Join-Path $InstallPath "logs\ricoh-monitor.err.log")
& $NssmExe set $ServiceName AppRotateFiles 1
& $NssmExe set $ServiceName AppRotateOnline 1
& $NssmExe set $ServiceName AppRotateBytes 10485760

New-Item -ItemType Directory -Force -Path (Join-Path $InstallPath "logs") | Out-Null

Write-Host "Service installed: $ServiceName" -ForegroundColor Green
Write-Host "Start it with: Start-Service $ServiceName"
