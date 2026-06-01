@echo off
setlocal
cd /d "%~dp0.."

if not exist "backend\.env" (
  echo ERROR: backend\.env no existe.
  echo Copia backend\.env.example a backend\.env y configura DATABASE_URL, APP_SECRET_KEY y EMERGENCY_ADMIN_PASSWORD.
  exit /b 1
)

if not exist "backend\venv\Scripts\python.exe" (
  echo ERROR: backend\venv no existe. Ejecuta scripts\windows_prepare_server.ps1 primero.
  exit /b 1
)

set HOST=0.0.0.0
set PORT=8000

cd backend
venv\Scripts\python.exe -m uvicorn app.main:app --host %HOST% --port %PORT%
