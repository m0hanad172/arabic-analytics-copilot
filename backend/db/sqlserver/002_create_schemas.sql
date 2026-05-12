/*
 * 002_create_schemas.sql  (Phase C3)
 *
 * Creates the bi and bi_meta schemas inside ArabicAnalytics.
 * Idempotent. Run while connected to the ArabicAnalytics database.
 */
USE ArabicAnalytics;
GO

IF SCHEMA_ID(N'bi') IS NULL
BEGIN
    PRINT N'Creating schema bi...';
    EXEC(N'CREATE SCHEMA bi AUTHORIZATION dbo');
END
ELSE
BEGIN
    PRINT N'Schema bi already exists.';
END
GO

IF SCHEMA_ID(N'bi_meta') IS NULL
BEGIN
    PRINT N'Creating schema bi_meta...';
    EXEC(N'CREATE SCHEMA bi_meta AUTHORIZATION dbo');
END
ELSE
BEGIN
    PRINT N'Schema bi_meta already exists.';
END
GO
