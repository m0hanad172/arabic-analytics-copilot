# Arabic Analytics Copilot

Arabic Analytics Copilot is an Arabic natural-language-to-SQL BI assistant.
It accepts Arabic business questions, compiles them into guarded analytics SQL,
executes against the BI schema, and returns rows, SQL, plan metadata, cache
status, and logs for review.

The project is now SQL Server-first for company operation. PostgreSQL remains
available as a fallback and legacy compatibility path until final approval.

## Current Production Target

- Operational database: Microsoft SQL Server
- Target database name: `ArabicAnalytics`
- Runtime schema: `bi`
- Metadata schema: `bi_meta`
- SQL Server runtime mode: `DATABASE_BACKEND=sqlserver`
- SQL Server compiler mode: `COMPILER_BACKEND=python`
- Temporary fallback mode: `DATABASE_BACKEND=postgres`, `COMPILER_BACKEND=db`

Do not commit local `.env` files or real passwords. Keep `backend/.env` local.

## Repository Layout

- `backend/app/`: FastAPI backend, SQL guardrails, compiler, catalog loader, DB adapter
- `backend/db/sqlserver/`: SQL Server schema and seed scripts
- `scripts/test_sqlserver_connection.py`: SQL Server connection probe
- `scripts/load_sqlserver_staging.py`: CSV loader for SQL Server staging/runtime data
- `scripts/smoke_sqlserver_ask.py`: SQL Server `/api/ask` smoke test
- `frontend/`: React/Vite dashboard
- `data/clean/bi_ready_clean.csv`: prepared BI CSV
- `docs/SQLSERVER_MIGRATION_PLAN.md`: migration status and phase notes
- `docs/DATABASE_MIGRATION.md`: backend database migration details
- `docs/PHASE_C_PLAN.md`: Phase C compiler and SQL Server plan

## SQL Server Setup

Install these prerequisites on the Windows host:

- SQL Server Express or SQL Server Developer Edition
- SQL Server Management Studio, recommended for initial setup
- ODBC Driver 18 for SQL Server
- Python virtual environment dependencies from `backend/requirements.txt`

Create or verify the database with SQL Server Management Studio or `sqlcmd`.
The schema scripts are idempotent and should be applied in order:

```powershell
sqlcmd -S .\SQLEXPRESS -E -i .\backend\db\sqlserver\001_create_database.sql
sqlcmd -S .\SQLEXPRESS -E -d ArabicAnalytics -i .\backend\db\sqlserver\002_create_schemas.sql
sqlcmd -S .\SQLEXPRESS -E -d ArabicAnalytics -i .\backend\db\sqlserver\003_create_bi_objects.sql
sqlcmd -S .\SQLEXPRESS -E -d ArabicAnalytics -i .\backend\db\sqlserver\004_create_bi_meta_objects.sql
sqlcmd -S .\SQLEXPRESS -E -d ArabicAnalytics -i .\backend\db\sqlserver\005_seed_bi_meta.sql
```

If using SQL Authentication instead of Windows Authentication, enable SQL
Server Mixed Mode and create an application login with read/write access to
`ArabicAnalytics`. Keep the password only in the local shell or local
`backend/.env`.

## SQL Server Environment

The helper scripts read `MSSQL_*` variables. SQL Authentication is used only
when both `MSSQL_USER` and `MSSQL_PASSWORD` are present; otherwise Windows
Trusted Connection is used.

Windows Authentication example:

```powershell
$env:MSSQL_SERVER=".\SQLEXPRESS"
$env:MSSQL_DRIVER="ODBC Driver 18 for SQL Server"
$env:MSSQL_DATABASE="ArabicAnalytics"
$env:PYTHONIOENCODING="utf-8"
```

SQL Authentication example:

```powershell
$env:MSSQL_SERVER=".\SQLEXPRESS"
$env:MSSQL_DRIVER="ODBC Driver 18 for SQL Server"
$env:MSSQL_DATABASE="ArabicAnalytics"
$env:MSSQL_USER="<sql_login>"
$env:MSSQL_PASSWORD="<sql_password>"
$env:PYTHONIOENCODING="utf-8"
```

`PYTHONIOENCODING=utf-8` avoids Arabic text rendering as question marks in
some Windows PowerShell sessions.

For SQLAlchemy, use the `odbc_connect=` URL form for SQL Server named
instances. Do not use the broken netloc form such as
`mssql+aioodbc://@.%5CSQLEXPRESS/...`.

Example shape:

```env
DATABASE_URL=mssql+aioodbc:///?odbc_connect=DRIVER%3D%7BODBC+Driver+18+for+SQL+Server%7D%3BSERVER%3D.%5CSQLEXPRESS%3BDATABASE%3DArabicAnalytics%3BTrusted_Connection%3Dyes%3BTrustServerCertificate%3Dyes%3BEncrypt%3Dno%3B
```

See `backend/.env.example` for placeholder-only examples for both Windows
Authentication and SQL Authentication.

## Load The CSV

After the SQL Server schema exists, load the clean BI CSV:

```powershell
.\.venv\Scripts\python.exe scripts\load_sqlserver_staging.py
```

The expected company smoke baseline is 5000 rows in:

- `dbo.bi_ready_clean`
- `bi.fact_sales_line`

## Run The Backend

Create and install the Python environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt
```

Set the SQL Server runtime mode locally:

```powershell
$env:DATABASE_BACKEND="sqlserver"
$env:COMPILER_BACKEND="python"
$env:MSSQL_SERVER=".\SQLEXPRESS"
$env:MSSQL_DRIVER="ODBC Driver 18 for SQL Server"
$env:MSSQL_DATABASE="ArabicAnalytics"
```

If using SQL Authentication, also set `MSSQL_USER` and `MSSQL_PASSWORD` in
the local shell.

Run FastAPI:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --reload --port 8000
```

API docs:

- http://localhost:8000/docs

## Run The Frontend

```powershell
cd frontend
npm install
npm run dev
```

The Vite app runs at:

- http://localhost:3000

## Smoke Tests

Probe SQL Server connectivity:

```powershell
python scripts/test_sqlserver_connection.py
```

Run the SQL Server `/api/ask` smoke:

```powershell
python scripts/smoke_sqlserver_ask.py
```

The smoke should confirm:

- `/api/health` returns 200
- `/api/ask` returns 200 for the Arabic test questions
- `meta.compiler_backend` is `python`
- `meta.catalog_source` is `sqlserver_tables`
- `meta.skipped_for_sqlserver` is `None`
- a `query_log` id is returned
- `plan_cache` reuse reports `used_cache=True`

Focused backend tests:

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/test_sqlserver_connect.py backend/tests/test_ask_cache_log.py backend/tests/test_ask_compiler_backend.py backend/tests/test_sqlserver_live_ask.py -q
```

SQL Server runtime reads `backend/.env`, so a local company setup may keep:

```env
DATABASE_BACKEND=sqlserver
COMPILER_BACKEND=python
```

Some tests intentionally verify the documented PostgreSQL/db fallback defaults.
Those tests isolate settings internally, but you can also run a default-behavior
pass from PowerShell with:

```powershell
$env:DATABASE_BACKEND="postgres"
$env:COMPILER_BACKEND="db"
.\.venv\Scripts\python.exe -m pytest backend/tests/test_db_adapter.py backend/tests/test_ask_compiler_backend.py -q
```

Optional live SQL Server pytest:

```powershell
$env:SQLSERVER_LIVE="1"
.\.venv\Scripts\python.exe -m pytest backend/tests/test_sqlserver_live_ask.py -q
```

Full pytest may require the legacy PostgreSQL Docker database. If full pytest
fails only with `127.0.0.1:5432` connection errors, treat that as a missing
PostgreSQL fallback environment, not a SQL Server regression.

## PostgreSQL Fallback

PostgreSQL is still present for fallback and historical compatibility. The
defaults in `backend/.env.example` intentionally remain:

```env
DATABASE_BACKEND=postgres
COMPILER_BACKEND=db
```

Start the PostgreSQL Docker fallback when needed:

```powershell
docker compose -f compose.db.yml -p aac up -d
```

Restore the legacy dump:

```powershell
docker exec -i aac-pg psql -U postgres -d arabic_analytics < db/db_dump.sql
```

Do not remove PostgreSQL code or migration files until the final SQL
Server-only approval is given.

## Troubleshooting

Connection fails with SQL Authentication:

- Confirm SQL Server Mixed Mode is enabled.
- Confirm the login maps to `ArabicAnalytics`.
- Confirm the login has at least `db_datareader` and `db_datawriter`.
- Run `python scripts/test_sqlserver_connection.py`.

Connection fails with Windows Authentication:

- Try setting `MSSQL_SERVER` to `.\SQLEXPRESS`, `{COMPUTERNAME}\SQLEXPRESS`,
  `localhost\SQLEXPRESS`, or `(local)\SQLEXPRESS`.
- The prober also tries named pipe and TCP fallbacks.

ODBC driver not found:

- Install ODBC Driver 18 for SQL Server.
- Confirm `MSSQL_DRIVER="ODBC Driver 18 for SQL Server"`.

Arabic appears as `????`:

- Set `$env:PYTHONIOENCODING="utf-8"`.
- Prefer the Python smoke scripts over ad-hoc PowerShell JSON bodies.

Named instance URL fails:

- Use SQLAlchemy `odbc_connect=`.
- Avoid `mssql+aioodbc://@.%5CSQLEXPRESS/...`.

Docker/PostgreSQL tests fail:

- Start the fallback database only when running legacy PostgreSQL tests.
- SQL Server C5 readiness is covered by the focused SQL Server tests and
  smoke scripts above.
