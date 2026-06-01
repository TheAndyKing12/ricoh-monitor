@echo off
setlocal
cd /d "%~dp0.."

if not exist "backend\.env" (
  if exist "backend\.env.example" (
    echo No existe backend\.env. Copiando backend\.env.example...
    copy /y backend\.env.example backend\.env >nul
  )
)

if exist "backend\venv\Scripts\python.exe" (
  backend\venv\Scripts\python.exe --version >nul 2>nul
  if errorlevel 1 (
    echo El entorno virtual existente no funciona. Recrendolo...
    rmdir /s /q backend\venv
  )
)

if not exist "backend\venv\Scripts\python.exe" (
  echo No existe backend\venv. Creando entorno virtual...
  py -3 -m venv backend\venv
)

echo Instalando dependencias...
backend\venv\Scripts\python.exe -m pip install -r backend\requirements.txt
if errorlevel 1 exit /b 1

set PORT=8000
powershell -NoProfile -Command "if (Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue) { exit 1 }"
if errorlevel 1 (
  set PORT=8000
)

echo Iniciando Ricoh Monitor en http://127.0.0.1:%PORT%/frontend/dashboard.html
cd backend
venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port %PORT% --reload
