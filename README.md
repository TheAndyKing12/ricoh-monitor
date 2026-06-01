# Ricoh Monitor

Dashboard local para monitorear impresoras Ricoh, contadores, toner, inventario y alertas.

## Requisitos

- Windows con Python 3.11 o superior
- Node.js para ejecutar el validador de JavaScript
- Acceso de red a las impresoras Ricoh

## Instalacion rapida

```powershell
cd C:\ricoh-monitor
copy backend\.env.example backend\.env
py -3 -m venv backend\venv
backend\venv\Scripts\python.exe -m pip install -r backend\requirements.txt
```

Configura `backend\.env` si necesitas cambiar valores locales. Ese archivo no debe versionarse; usa `backend\.env.example` como plantilla:

```env
DATABASE_URL=sqlite:///./ricoh.db
APP_SECRET_KEY=cambia-este-secreto
STATUS_SYNC_INTERVAL=5
COUNTER_SYNC_INTERVAL=30
TONER_SYNC_INTERVAL=10
CORS_ORIGINS=*
ALERT_WEBHOOK_URL=
```

## Login

Para entrar por primera vez usa el usuario local de emergencia definido en `backend\.env`:

```text
Usuario: admin
Contrasena: change-me
```

Cambia `EMERGENCY_ADMIN_PASSWORD` en `backend\.env` antes de usar el sistema en produccion. Si Active Directory esta configurado, tambien puedes entrar con usuarios AD que hayan sido habilitados desde Configuracion.

## Arranque

```powershell
scripts\start_backend.bat
```

Luego abre:

[http://127.0.0.1:8000/frontend/dashboard.html](http://127.0.0.1:8000/frontend/dashboard.html)

## Verificaciones

```powershell
node check_js.js
backend\venv\Scripts\python.exe scripts\check_backend.py
```

## Despliegue en Windows Server con SQL Server

La guia completa esta en:

[docs/DEPLOY_WINDOWS_SQLSERVER.md](docs/DEPLOY_WINDOWS_SQLSERVER.md)

Incluye creacion de base SQL Server, configuracion de `DATABASE_URL`, arranque productivo, firewall y servicio Windows con NSSM.

## Endpoints utiles

- `GET /health`: estado de API, base de datos, cache y scheduler.
- `GET /scheduler/status`: trabajos programados y ultimas ejecuciones.
- `POST /scheduler/sync-status-now`: sincroniza estado.
- `POST /scheduler/sync-counters-now`: sincroniza contadores.
- `POST /scheduler/sync-toner-now`: sincroniza control de toner.
- `POST /notifications/test`: dispara una alerta de prueba local y webhook si esta configurado.

## Notas de mantenimiento

- No versionar `venv`, `__pycache__`, bases `.db` ni `.env`.
- Si agregas tablas o columnas nuevas, pon la migracion en `backend/app/migrations.py`.
- Mantén `backend/requirements.txt` alineado con imports reales del backend.
- Para alertas externas, configura `ALERT_WEBHOOK_URL` con un webhook de Teams, Power Automate, Slack u otro receptor HTTP.
