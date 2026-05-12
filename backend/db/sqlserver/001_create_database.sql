/*
 * 001_create_database.sql  (Phase C3)
 *
 * Creates the ArabicAnalytics database on the current SQL Server
 * instance if it does not already exist. Idempotent.
 *
 * Connect to: master (or the default database) before running this
 * script. Subsequent scripts (002..005) expect the connection to be
 * switched to ArabicAnalytics.
 */
IF DB_ID(N'ArabicAnalytics') IS NULL
BEGIN
    PRINT N'Creating database ArabicAnalytics...';
    CREATE DATABASE ArabicAnalytics;
END
ELSE
BEGIN
    PRINT N'Database ArabicAnalytics already exists; skipping CREATE DATABASE.';
END
GO
