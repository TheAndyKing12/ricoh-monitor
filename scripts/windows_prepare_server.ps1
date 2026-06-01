param(
    [string]$InstallPath = "C:\ricoh-monitor",
    [switch]$SkipPipInstall
)

$ErrorActionPreference = "Stop"

Write-Host "Ricoh Monitor - Windows server preparation" -ForegroundColor Cyan

if (-not (Test-Path $InstallPath)) {
    throw "Install path not found: $InstallPath"
}

Set-Location $InstallPath

if (-not (Test-Path "backend\.env") -and (Test-Path "backend\.env.example")) {
    Copy-Item "backend\.env.example" "backend\.env"
    Write-Host "Created backend\.env from backend\.env.example" -ForegroundColor Yellow
    Write-Host "Edit backend\.env before starting the service." -ForegroundColor Yellow
}

if (-not (Test-Path "backend\venv\Scripts\python.exe")) {
    Write-Host "Creating Python virtual environment..."
    py -3 -m venv backend\venv
}

if (-not $SkipPipInstall) {
    Write-Host "Installing Python dependencies..."
    backend\venv\Scripts\python.exe -m pip install --upgrade pip
    backend\venv\Scripts\python.exe -m pip install -r backend\requirements.txt
}

Write-Host "Checking backend imports..."
backend\venv\Scripts\python.exe scripts\check_backend.py

Write-Host ""
Write-Host "Next steps:" -ForegroundColor Green
Write-Host "1. Install Microsoft ODBC Driver 18 for SQL Server if it is not installed."
Write-Host "2. Run scripts\sqlserver_create_database.sql in SQL Server Management Studio."
Write-Host "3. Edit backend\.env with your SQL Server DATABASE_URL."
Write-Host "4. Test: scripts\start_production.bat"
Write-Host "5. Open: http://SERVER_NAME:8000/frontend/dashboard.html"
