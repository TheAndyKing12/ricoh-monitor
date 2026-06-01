/*
  Ricoh Monitor - SQL Server database bootstrap

  Run this in SQL Server Management Studio as a sysadmin or database admin.
  Change the password before using it in production.
*/

IF DB_ID(N'RicohMonitor') IS NULL
BEGIN
    CREATE DATABASE RicohMonitor;
END;
GO

USE RicohMonitor;
GO

IF NOT EXISTS (SELECT 1 FROM sys.server_principals WHERE name = N'ricoh_user')
BEGIN
    CREATE LOGIN ricoh_user WITH PASSWORD = 'ChangeThisPassword!2026', CHECK_POLICY = ON;
END;
GO

IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = N'ricoh_user')
BEGIN
    CREATE USER ricoh_user FOR LOGIN ricoh_user;
END;
GO

ALTER ROLE db_datareader ADD MEMBER ricoh_user;
ALTER ROLE db_datawriter ADD MEMBER ricoh_user;
ALTER ROLE db_ddladmin ADD MEMBER ricoh_user;
GO

SELECT DB_NAME() AS database_name, name AS user_name
FROM sys.database_principals
WHERE name = N'ricoh_user';
GO
