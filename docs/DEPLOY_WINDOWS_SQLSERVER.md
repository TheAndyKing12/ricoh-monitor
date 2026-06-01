# Deploy Ricoh Monitor on Windows Server with SQL Server

This guide assumes:

- Windows Server 2019/2022 or Windows 10/11 used as a server.
- Microsoft SQL Server is installed locally or reachable on the network.
- Python 3.11+ is installed.
- The app folder is `C:\ricoh-monitor`.

## 1. Install server prerequisites

Install these on the server:

- Python 3.11 or newer.
- Microsoft ODBC Driver 18 for SQL Server.
- Git, or copy the project folder manually.
- Optional: NSSM if you want to run the app as a Windows service.

ODBC driver download:

`https://learn.microsoft.com/sql/connect/odbc/download-odbc-driver-for-sql-server`

## 2. Copy the application

Put the project in:

```powershell
C:\ricoh-monitor
```

If you copy it from another machine, do not copy:

- `backend\venv`
- `backend\.env`
- `*.db`
- `backend\cache`
- `backend\data`

## 3. Create the SQL Server database

Open SQL Server Management Studio as an admin and run:

```sql
scripts\sqlserver_create_database.sql
```

Change the login password inside that script before production use.

The script creates:

- Database: `RicohMonitor`
- Login/user: `ricoh_user`
- Required permissions for table creation and app reads/writes.

## 4. Prepare Python environment

Run PowerShell as Administrator:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope Process
cd C:\ricoh-monitor
.\scripts\windows_prepare_server.ps1
```

This creates `backend\venv`, installs dependencies and creates `backend\.env` if missing.

## 5. Configure backend\.env

Edit:

```text
C:\ricoh-monitor\backend\.env
```

Recommended SQL login configuration:

```env
DATABASE_URL=mssql+pyodbc://ricoh_user:ChangeThisPassword!2026@localhost/RicohMonitor?driver=ODBC+Driver+18+for+SQL+Server&TrustServerCertificate=yes
APP_SECRET_KEY=generate-a-long-random-secret-here
EMERGENCY_ADMIN_USER=admin
EMERGENCY_ADMIN_PASSWORD=change-this-now
TOKEN_EXPIRE_HOURS=8
STATUS_SYNC_INTERVAL=5
COUNTER_SYNC_INTERVAL=30
TONER_SYNC_INTERVAL=10
CORS_ORIGINS=*
ALERT_WEBHOOK_URL=
ALERT_WEBHOOK_TIMEOUT_SECONDS=5
CACHE_DIR=cache
ADDRESS_BOOK_BROWSER_LOGIN_ENABLED=0
ADDRESS_BOOK_DEBUG_ENDPOINTS_ENABLED=0
```

Windows Authentication alternative:

```env
DATABASE_URL=mssql+pyodbc://@localhost/RicohMonitor?driver=ODBC+Driver+18+for+SQL+Server&trusted_connection=yes&TrustServerCertificate=yes
```

If your password has special characters such as `@`, `#`, `%`, `/`, `?` or `&`, URL-encode it.

## 6. Test database connection

```powershell
cd C:\ricoh-monitor
backend\venv\Scripts\python.exe scripts\test_database_connection.py
```

Expected output:

```text
database ok: 1
dialect: mssql
```

## 7. Start manually first

```powershell
cd C:\ricoh-monitor
.\scripts\start_production.bat
```

Open:

```text
http://SERVER_NAME:8000/frontend/dashboard.html
```

First login uses the emergency admin values from `.env`.

## 8. Open Windows Firewall

Run as Administrator:

```powershell
New-NetFirewallRule -DisplayName "Ricoh Monitor 8000" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow
```

## 9. Install as Windows service with NSSM

Download NSSM and place `nssm.exe` at:

```text
C:\nssm\nssm.exe
```

Then run:

```powershell
cd C:\ricoh-monitor
.\scripts\install_windows_service_nssm.ps1
Start-Service RicohMonitor
```

Service logs are written to:

```text
C:\ricoh-monitor\logs
```

Useful commands:

```powershell
Get-Service RicohMonitor
Restart-Service RicohMonitor
Stop-Service RicohMonitor
```

## 10. Health check

```powershell
Invoke-WebRequest http://127.0.0.1:8000/health -UseBasicParsing
```

The response should include:

- `status: ok`
- `database.ok: true`
- scheduler information
- cache information

## 11. Production checklist

- Change `APP_SECRET_KEY`.
- Change `EMERGENCY_ADMIN_PASSWORD`.
- Use a strong SQL password.
- Keep `backend\.env` private.
- Disable debug address book endpoints unless needed.
- Restrict firewall access to trusted networks if possible.
- Configure Active Directory from the admin UI after first login.
- Create real admin users and disable/remove emergency admin access if your policy requires it.

## 12. Updating the app later

Stop service:

```powershell
Stop-Service RicohMonitor
```

Update files, then run:

```powershell
cd C:\ricoh-monitor
backend\venv\Scripts\python.exe -m pip install -r backend\requirements.txt
backend\venv\Scripts\python.exe scripts\check_backend.py
Start-Service RicohMonitor
```

The app runs startup migrations automatically when it starts.
