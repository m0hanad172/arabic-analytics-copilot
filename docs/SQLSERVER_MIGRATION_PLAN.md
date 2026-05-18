# SQL Server Migration Plan

Phase C3 deliverable. This document describes how to stand up the
ArabicAnalytics database on Microsoft SQL Server, and what the Phase C3
code changes do.

## Production readiness status

As of 2026-05-19, SQL Server is the primary company runtime for Arabic
Analytics Copilot. The verified runtime is:

- `DATABASE_BACKEND=sqlserver`
- `COMPILER_BACKEND=python`
- SQL Server database `ArabicAnalytics`
- semantic catalog loaded from SQL Server `bi_meta` tables
- plan cache and query log persisted in SQL Server
- Python compiler emitting guarded T-SQL

The SQL Server connection probe, `/api/ask` smoke script, and acceptance
question suite have passed. LLM planning may be enabled, but the runtime must
continue to work when provider quota is exhausted by falling back to the
rule-based planner.

PostgreSQL remains available only as a legacy fallback until a separate
SQL-Server-only removal phase is approved.

## Target environment

| | |
|---|---|
| Server instance | `.\SQLEXPRESS` or `<COMPUTERNAME>\SQLEXPRESS` |
| Database | `ArabicAnalytics` |
| Schemas | `bi`, `bi_meta` |
| Connection style | Windows trusted auth, or SQL auth when Mixed Mode is enabled |
| ODBC driver | `ODBC Driver 18 for SQL Server` or `ODBC Driver 17 for SQL Server` |

Example SQLAlchemy URL (used by `backend/.env.example`):

```env
DATABASE_BACKEND=sqlserver
COMPILER_BACKEND=python
DATABASE_URL=mssql+aioodbc:///?odbc_connect=DRIVER%3D%7BODBC+Driver+18+for+SQL+Server%7D%3BSERVER%3D.%5CSQLEXPRESS%3BDATABASE%3DArabicAnalytics%3BTrusted_Connection%3Dyes%3BTrustServerCertificate%3Dyes%3BEncrypt%3Dno%3B
```

Always use SQLAlchemy's `odbc_connect=` form for SQL Server named
instances. Do **not** use the old `mssql+...://@.%5CSQLEXPRESS/...`
netloc style: aioodbc can pass the literal `%5C` through to pyodbc,
which breaks named-instance resolution.

The async path uses `aioodbc` (`mssql+aioodbc://...`). Install the SQL
Server Python drivers locally before exercising the live runtime:

```powershell
pip install aioodbc pyodbc
```

## PostgreSQL source audit (read-only)

Captured live from `arabic_analytics` on `127.0.0.1:5432` for the
Phase C3 port. Full export at `docs/.bi_meta_export.json` (gitignored;
regenerate with the helper script described below).

### `bi` schema

- `bi.fact_sales_line` (base table, 28 columns) — see column list below.
- `bi.vw_fact_sales_line_clean` (view) — exposes the columns the
  compiler/catalog reference. Adds `order_date_d` / `ship_date_d`
  aliases for `order_date` / `ship_date`, and pre-computes
  `order_year`, `order_month`, `order_quarter`.
- Other views (`vw_sales_by_*`, `vw_sales_monthly`, `vw_shipping_kpis`)
  exist in PG but `/ask` does not use them; Phase C3 ports only the
  fact table and the clean view.

`bi.vw_fact_sales_line_clean` columns (`text`, `integer`, `date`,
`numeric` in PG → mapped to T-SQL types in Phase C3 scripts):

| PG type | T-SQL type |
|---|---|
| `text` | `NVARCHAR(400)` (or `NVARCHAR(MAX)` for very long fields) |
| `integer` | `INT` |
| `date` | `DATE` |
| `numeric` | `DECIMAL(38, 6)` |
| `timestamptz` | `DATETIMEOFFSET` |
| `jsonb` | `NVARCHAR(MAX)` (parsed in Python; SQL Server 2022+ has native `JSON` but we stay portable) |

### `bi_meta`

| Object | Rows | Notes |
|---|---|---|
| `bi_meta.metrics` | 13 | `metric_key, display_name_ar, display_name_en, agg, sql_expression, data_type, format_hint`. PG `sql_expression` values use `sum(f.x::numeric)` / `count(*)::bigint`. T-SQL versions strip `::cast` and use `COUNT_BIG(*)`. |
| `bi_meta.dimensions` | 13 | `dim_key, display_name_ar, display_name_en, sql_expression, data_type, allowed_grouping`. PG expressions for date buckets use `extract(...)::int` / `date_trunc(...)::date`; T-SQL versions use `DATEPART` and `DATEFROMPARTS`. |
| `bi_meta.synonyms` | 54 | `term, maps_to_type, maps_to_key`. No PG-specific syntax; ported verbatim. |
| `bi_meta.plan_cache` | n/a | `id BIGINT PK, question_norm, question_raw, catalog_hash, plan jsonb, model, hits, created_at, updated_at, last_used_at`. T-SQL `plan` column is `NVARCHAR(MAX)`. Upsert via `MERGE` in Phase C4. |
| `bi_meta.query_log` | n/a | `id, created_at, question, plan jsonb, sql, row_count, warnings jsonb, suggestions jsonb, duration_ms, used_cache, used_llm, [explain_used]`. T-SQL `jsonb` columns become `NVARCHAR(MAX)`. |

### PostgreSQL-specific syntax that disappears in the SQL Server seed

| PG construct | T-SQL replacement | Where it appears |
|---|---|---|
| `::numeric` | none (omit cast; SUM/AVG return DECIMAL naturally) | every numeric metric `sql_expression` |
| `count(*)::bigint` | `COUNT_BIG(*)` | `line_count`, `order_count` metrics |
| `extract(year from f.order_date_d)::int` | `DATEPART(year, f.order_date_d)` | `order_year`, `order_month`, `order_quarter` |
| `date_trunc('month', f.order_date_d)::date` | `DATEFROMPARTS(YEAR(f.order_date_d), MONTH(f.order_date_d), 1)` | `month_start` |
| `jsonb` | `NVARCHAR(MAX)` | `plan_cache.plan`, `query_log.{plan,warnings,suggestions}` |
| `ON CONFLICT (...)` | `MERGE` (Phase C4) | plan_cache upsert |
| `now()` | `SYSUTCDATETIME()` | `plan_cache`/`query_log` defaults |
| `ILIKE` | `LIKE` (CI collation) | dialect-aware via Phase A |
| `LIMIT n` | `TOP (n)` | dialect-aware via Phase A |

## How to apply the SQL Server scripts (SSMS)

1. Open SQL Server Management Studio (SSMS).
2. Connect to `.\SQLEXPRESS` (or the server name shown by SSMS) with
   Windows authentication or SQL authentication.
3. Open and execute the scripts in order from
   `backend/db/sqlserver/`:

   ```
   001_create_database.sql
   002_create_schemas.sql
   003_create_bi_objects.sql
   004_create_bi_meta_objects.sql
   005_seed_bi_meta.sql
   ```

   The scripts are idempotent (`IF NOT EXISTS` / `MERGE` guards) so it
   is safe to re-run them.

4. Load data into `bi.fact_sales_line` from the PostgreSQL export
   (`data/clean/bi_ready_clean.csv` is the existing source of truth).
   Use SSMS's *Import Flat File…* or the `bcp` utility — Phase C3 does
   **not** ship a data-load script.

5. From the project venv:

   ```powershell
   pip install aioodbc pyodbc
   ```

6. Set the SQL Server URL in `backend/.env` using `odbc_connect=`.
   `backend/.env` is gitignored and **must not** be committed.

   ```env
   DATABASE_BACKEND=sqlserver
   COMPILER_BACKEND=python
   DATABASE_URL=mssql+aioodbc:///?odbc_connect=DRIVER%3D%7BODBC+Driver+18+for+SQL+Server%7D%3BSERVER%3D.%5CSQLEXPRESS%3BDATABASE%3DArabicAnalytics%3BTrusted_Connection%3Dyes%3BTrustServerCertificate%3Dyes%3BEncrypt%3Dno%3B
   ```

   For SQL authentication, enable Mixed Mode in SQL Server and use
   `UID`/`PWD` placeholders in the ODBC string. Keep the real password
   local only:

   ```env
   DATABASE_URL=mssql+aioodbc:///?odbc_connect=DRIVER%3D%7BODBC+Driver+18+for+SQL+Server%7D%3BSERVER%3D.%5CSQLEXPRESS%3BDATABASE%3DArabicAnalytics%3BUID%3D%3Csql_login%3E%3BPWD%3D%3Csql_password%3E%3BTrustServerCertificate%3Dyes%3BEncrypt%3Dno%3B
   ```

7. Boot the backend (`uvicorn ...`) and try `/ask` with a question
   that only uses supported metrics/dimensions.

## SQL Server Express connection troubleshooting (Phase C4 hotfix)

SSMS connecting fine while pyodbc fails often means a named-instance
discovery, protocol, encryption, or authentication-mode problem. Work
through this list before changing application code:

### 1. SQL Server Browser

The Browser service answers UDP/1434 with the named instance's TCP port.
Without it, `MOHANADLENOVO\SQLEXPRESS` is unresolvable to anything except
SSMS (which has its own discovery path).

- Open `services.msc`, find **SQL Server Browser**, start it, set startup
  type to *Automatic*.

### 2. TCP/IP enabled

Default SQL Server Express installs leave **TCP/IP disabled** on named
instances. Without it, only shared memory (same-machine) works, and only
some drivers will use shared memory by default.

- Open **SQL Server Configuration Manager** →
  **SQL Server Network Configuration** → **Protocols for SQLEXPRESS**.
- Right-click **TCP/IP** → Enable.
- Under **SQL Server Services**, right-click **SQL Server (SQLEXPRESS)** →
  Restart.

### 3. Shared Memory

Shared Memory works only for processes on the **same** machine. If a
"Shared Memory connection to a *remote* SQL Server instance" error
appears (which is what `lpc:` triggers when pyodbc thinks it's remote),
fall back to the named-pipe or TCP forms.

### 4. Named-instance discovery

If `MOHANADLENOVO\SQLEXPRESS` fails but `.\SQLEXPRESS` or
`localhost\SQLEXPRESS` works, SQL Server Browser is probably off (see #1).

### 5. ODBC Driver 18: encryption defaults

Driver 18 turns on **Encrypt=yes** by default, which trips on a local
dev box with no trusted certificate. Use one of:

- `Encrypt=no` (simplest for local dev), or
- `TrustServerCertificate=yes` (still encrypts but accepts the local cert).

The Phase C4 connection-string builder
(`backend/app/db/sqlserver_connect.build_connection_string`) emits
`TrustServerCertificate=yes` by default and lets the caller opt into
`Encrypt=`.

### 6. SQL authentication / Mixed Mode

If Windows `Trusted_Connection` fails from pyodbc/aioodbc with a
security-package error, SQL authentication is a valid local smoke path.
Enable Mixed Mode in SQL Server, create a least-privilege login/user for
`ArabicAnalytics`, and grant `db_datareader` / `db_datawriter`. Store
the password only in your local shell or gitignored `.env`; never commit
it. The helper scripts use SQL auth only when both `MSSQL_USER` and
`MSSQL_PASSWORD` are set, and they mask `PWD` in printed connection
strings.

### 7. Probe scripts

```powershell
# Walk through driver/server combos and print the working one.
$env:PYTHONIOENCODING = "utf-8"       # helps PowerShell print Arabic safely
python scripts/test_sqlserver_connection.py

# Optional SQL auth path. Set the password locally; do not commit it.
$env:MSSQL_SERVER = ".\SQLEXPRESS"
$env:MSSQL_DRIVER = "ODBC Driver 18 for SQL Server"
$env:MSSQL_DATABASE = "ArabicAnalytics"
$env:MSSQL_USER = "<sql_login>"
$env:MSSQL_PASSWORD = "<sql_password>"
python scripts/test_sqlserver_connection.py

# Once a combo works, stage the CSV into dbo.bi_ready_clean:
$env:MSSQL_SERVER = ".\SQLEXPRESS"     # from the probe output
python scripts/load_sqlserver_staging.py
```

Environment overrides accepted by both scripts:

| Variable | Purpose |
|---|---|
| `MSSQL_SERVER` | `SERVER=` value (e.g. `.\SQLEXPRESS`, `tcp:localhost,1433`). |
| `MSSQL_DRIVER` | ODBC driver display name. Defaults to highest-priority installed. |
| `MSSQL_DATABASE` | Target database (default: `ArabicAnalytics`). |
| `MSSQL_USER` | Optional SQL-auth login. Requires `MSSQL_PASSWORD`. |
| `MSSQL_PASSWORD` | Optional SQL-auth password. Masked in script output; keep local only. |

### 8. Connection-string patterns tried by the probe

In priority order (cheap/local first, then TCP fallbacks):

```
.\SQLEXPRESS
<COMPUTERNAME>\SQLEXPRESS
<SQL Server OriginalMachineName>\SQLEXPRESS
localhost\SQLEXPRESS
(local)\SQLEXPRESS
lpc:.\SQLEXPRESS
np:\\.\pipe\MSSQL$SQLEXPRESS\sql\query
tcp:localhost,1433
tcp:127.0.0.1,1433
```

`OriginalMachineName` covers renamed Windows machines where SSMS and
`@@SERVERNAME` still report the name SQL Server had at install time.

### 9. Moving staged rows into `bi.fact_sales_line`

After `dbo.bi_ready_clean` is populated, run this once in SSMS to copy
the columns that match `bi.fact_sales_line`:

```sql
USE ArabicAnalytics;

TRUNCATE TABLE bi.fact_sales_line;

INSERT INTO bi.fact_sales_line (
    order_no, order_date, ship_date, ship_delay_days,
    customer_type, account_manager, order_priority,
    product_name, product_category, product_container, ship_mode,
    city, state,
    cost_price, retail_price, order_quantity,
    sub_total, discount_pct, discount_amount, order_total,
    shipping_cost, total, cogs, gross_profit, profit_after_shipping,
    order_year, order_month, order_quarter
)
SELECT
    NULLIF(order_no, ''),
    TRY_CONVERT(DATE, NULLIF(order_date, '')),
    TRY_CONVERT(DATE, NULLIF(ship_date, '')),
    TRY_CONVERT(INT,  NULLIF(ship_delay_days, '')),
    NULLIF(customer_type, ''), NULLIF(account_manager, ''),
    NULLIF(order_priority, ''),
    NULLIF(product_name, ''), NULLIF(product_category, ''),
    NULLIF(product_container, ''), NULLIF(ship_mode, ''),
    NULLIF(city, ''), NULLIF(state, ''),
    TRY_CONVERT(DECIMAL(38, 6), NULLIF(cost_price, '')),
    TRY_CONVERT(DECIMAL(38, 6), NULLIF(retail_price, '')),
    TRY_CONVERT(INT,            NULLIF(order_quantity, '')),
    TRY_CONVERT(DECIMAL(38, 6), NULLIF(sub_total, '')),
    TRY_CONVERT(DECIMAL(38, 6), NULLIF(discount_pct, '')),
    TRY_CONVERT(DECIMAL(38, 6), NULLIF(discount_amount, '')),
    TRY_CONVERT(DECIMAL(38, 6), NULLIF(order_total, '')),
    TRY_CONVERT(DECIMAL(38, 6), NULLIF(shipping_cost, '')),
    TRY_CONVERT(DECIMAL(38, 6), NULLIF(total, '')),
    TRY_CONVERT(DECIMAL(38, 6), NULLIF(cogs, '')),
    TRY_CONVERT(DECIMAL(38, 6), NULLIF(gross_profit, '')),
    TRY_CONVERT(DECIMAL(38, 6), NULLIF(profit_after_shipping, '')),
    TRY_CONVERT(INT, NULLIF(order_year, '')),
    TRY_CONVERT(INT, NULLIF(order_month, '')),
    TRY_CONVERT(INT, NULLIF(order_quarter, ''))
FROM dbo.bi_ready_clean;
```

`TRY_CONVERT` returns `NULL` (not an error) for cells that cannot be
parsed, which is what we want — the Phase C3 ALTER block already made
every business column nullable.

## Phase C5 live SQL Server smoke test

**Date verified:** Phase C5. Backend: `.\SQLEXPRESS` / local
`SQLEXPRESS`, database `ArabicAnalytics`, driver `ODBC Driver 18 for SQL
Server`. Tested end-to-end with the in-process TestClient in
`scripts/smoke_sqlserver_ask.py`.

### Working SERVER pattern

```
DRIVER={ODBC Driver 18 for SQL Server}
SERVER=.\SQLEXPRESS
DATABASE=ArabicAnalytics
Trusted_Connection=yes
TrustServerCertificate=yes
Encrypt=no
```

### Working SQL-auth pattern

Use this when Mixed Mode is enabled and a database user has
`db_datareader` / `db_datawriter`. Keep the real password local only.

```
DRIVER={ODBC Driver 18 for SQL Server}
SERVER=.\SQLEXPRESS
DATABASE=ArabicAnalytics
UID=<sql_login>
PWD=<sql_password>
TrustServerCertificate=yes
Encrypt=no
```

### Working DATABASE_URL

```env
DATABASE_BACKEND=sqlserver
COMPILER_BACKEND=python
DATABASE_URL=mssql+aioodbc:///?odbc_connect=DRIVER%3D%7BODBC+Driver+18+for+SQL+Server%7D%3BSERVER%3D.%5CSQLEXPRESS%3BDATABASE%3DArabicAnalytics%3BTrusted_Connection%3Dyes%3BTrustServerCertificate%3Dyes%3BEncrypt%3Dno%3B
```

> **Why `odbc_connect=` instead of a normal netloc URL?** The named
> instance "`.\SQLEXPRESS`" has a backslash. URL-encoding it as `%5C` in
> the host part does not survive aioodbc's pyodbc bridge — the driver
> receives a literal `.%5CSQLEXPRESS` and reports
> `Named Pipes Provider: Could not open a connection ... [53]`.
> `odbc_connect=<url-encoded ODBC string>` passes the raw connection
> string through SQLAlchemy unchanged, which is the form SQLAlchemy's
> own docs recommend for SQL Server.

### Staging loader command

```powershell
$env:MSSQL_SERVER = ".\SQLEXPRESS"   # discovered by the probe
python scripts/load_sqlserver_staging.py
# -> Loaded 5000 rows into dbo.bi_ready_clean
```

### Transfer staging -> bi.fact_sales_line (corrected)

INT-target columns must use a **two-step decimal-then-int cast** because
pandas serialises ints-with-nulls as float strings like `'23.0'`, and
`TRY_CONVERT(INT, '23.0')` returns NULL. The block below is the version
that loaded 5000 rows with **0 unintended NULLs**:

```sql
USE ArabicAnalytics;
TRUNCATE TABLE bi.fact_sales_line;
INSERT INTO bi.fact_sales_line (
    order_no, order_date, ship_date, ship_delay_days,
    customer_type, account_manager, order_priority,
    product_name, product_category, product_container, ship_mode,
    city, state,
    cost_price, retail_price, order_quantity,
    sub_total, discount_pct, discount_amount, order_total,
    shipping_cost, total, cogs, gross_profit, profit_after_shipping,
    order_year, order_month, order_quarter
)
SELECT
    NULLIF(order_no, ''),
    TRY_CONVERT(DATE, NULLIF(order_date, '')),
    TRY_CONVERT(DATE, NULLIF(ship_date, '')),
    CAST(TRY_CONVERT(DECIMAL(38, 6), NULLIF(ship_delay_days, '')) AS INT),
    NULLIF(customer_type, ''), NULLIF(account_manager, ''),
    NULLIF(order_priority, ''),
    NULLIF(product_name, ''), NULLIF(product_category, ''),
    NULLIF(product_container, ''), NULLIF(ship_mode, ''),
    NULLIF(city, ''), NULLIF(state, ''),
    TRY_CONVERT(DECIMAL(38, 6), NULLIF(cost_price, '')),
    TRY_CONVERT(DECIMAL(38, 6), NULLIF(retail_price, '')),
    CAST(TRY_CONVERT(DECIMAL(38, 6), NULLIF(order_quantity, '')) AS INT),
    TRY_CONVERT(DECIMAL(38, 6), NULLIF(sub_total, '')),
    TRY_CONVERT(DECIMAL(38, 6), NULLIF(discount_pct, '')),
    TRY_CONVERT(DECIMAL(38, 6), NULLIF(discount_amount, '')),
    TRY_CONVERT(DECIMAL(38, 6), NULLIF(order_total, '')),
    TRY_CONVERT(DECIMAL(38, 6), NULLIF(shipping_cost, '')),
    TRY_CONVERT(DECIMAL(38, 6), NULLIF(total, '')),
    TRY_CONVERT(DECIMAL(38, 6), NULLIF(cogs, '')),
    TRY_CONVERT(DECIMAL(38, 6), NULLIF(gross_profit, '')),
    TRY_CONVERT(DECIMAL(38, 6), NULLIF(profit_after_shipping, '')),
    CAST(TRY_CONVERT(DECIMAL(38, 6), NULLIF(order_year, '')) AS INT),
    CAST(TRY_CONVERT(DECIMAL(38, 6), NULLIF(order_month, '')) AS INT),
    CAST(TRY_CONVERT(DECIMAL(38, 6), NULLIF(order_quarter, '')) AS INT);
```

### Known issue: order_quantity was NULL after the first transfer

**Symptom:** every `bi.fact_sales_line.order_quantity` row was NULL even
though the CSV had `4999 / 5000` non-null values.

**Root cause:** the original transfer used `TRY_CONVERT(INT, NULLIF(order_quantity, ''))`.
The staging cell stores `'23.0'` (pandas read the column as `float64`
because one row is NaN, then pyodbc bound it as the text `'23.0'`).
SQL Server's `TRY_CONVERT(INT, '23.0')` returns NULL because the
literal contains a `.`.

**Fix:** wrap with `CAST(TRY_CONVERT(DECIMAL(38, 6), ...) AS INT)` for
every INT-target column. Doc above already uses this form.

After the corrected re-run:
- `SELECT COUNT(*) FROM bi.fact_sales_line` → 5 000.
- `SELECT COUNT(*) FROM bi.fact_sales_line WHERE order_quantity IS NULL` → 1 (matches the single CSV row that was genuinely NaN).
- `SELECT SUM(order_quantity) FROM bi.fact_sales_line` → 132 389.

### Tested Arabic questions (POST /api/ask)

All three returned HTTP 200, `meta.compiler_backend = "python"`,
`meta.catalog_source = "sqlserver_tables"`, and
`meta.skipped_for_sqlserver = None`. No asyncpg call, no
`bi_meta.compile_query` call.

| Question | Rows | Generated SQL |
|---|---:|---|
| اعرض عدد الطلبات حسب المدينة واعرض أعلى 5 | 2 | `SELECT TOP (5) f.city AS [city], COUNT_BIG(*) AS [order_count] FROM bi.vw_fact_sales_line_clean f WHERE 1=1 GROUP BY f.city ORDER BY [order_count] DESC;` |
| اعرض المبيعات حسب السنة | 5 | `SELECT TOP (200) DATEPART(year, f.order_date_d) AS [order_year], CAST(SUM(f.order_total) AS NUMERIC(38, 6)) AS [net_sales] FROM bi.vw_fact_sales_line_clean f WHERE 1=1 GROUP BY DATEPART(year, f.order_date_d) ORDER BY [net_sales] DESC;` |
| اعرض الربح حسب فئة المنتج | 3 | `SELECT TOP (200) f.product_category AS [product_category], CAST(SUM(f.gross_profit) AS NUMERIC(38, 6)) AS [gross_profit] FROM bi.vw_fact_sales_line_clean f WHERE 1=1 GROUP BY f.product_category ORDER BY [gross_profit] DESC;` |

Sanity checks on the first response:
- `result.rows[0]` → `{"city": "Sydney", "order_count": 3584}`
- No `LIMIT`, `::bigint`, `::numeric`, `ILIKE`, `jsonb` anywhere in any
  emitted SQL.

### Reproducing the live smoke

```powershell
pip install aioodbc pyodbc
$env:MSSQL_SERVER = ".\SQLEXPRESS"
$env:MSSQL_DRIVER = "ODBC Driver 18 for SQL Server"
$env:MSSQL_DATABASE = "ArabicAnalytics"
# Optional SQL-auth path. Set these only in your local shell.
$env:MSSQL_USER = "<sql_login>"
$env:MSSQL_PASSWORD = "<sql_password>"
$env:PYTHONIOENCODING = "utf-8"
python scripts/smoke_sqlserver_ask.py
```

`PYTHONIOENCODING=utf-8` avoids Windows PowerShell `cp1252` print
errors when the script prints Arabic questions. The script sets the app
backend/compiler overrides in-process via `os.environ`, mounts the
FastAPI app with `TestClient`, and prints the emitted SQL + the `meta`
block for each question. It does not touch `backend/.env`, and helper
output masks SQL passwords.

Expected Phase C5 smoke result:

- `/api/health` returns HTTP 200.
- `/api/ask` returns HTTP 200 for the three Arabic questions.
- `meta.compiler_backend = "python"`.
- `meta.catalog_source = "sqlserver_tables"`.
- `meta.skipped_for_sqlserver = None`.
- `meta.log_id` is present from `bi_meta.query_log`.
- The cache recheck returns `used_cache = True` from `bi_meta.plan_cache`.

## What Phase C3 ships in code

- `backend/db/sqlserver/*.sql` — schema + seed scripts (this document).
- `backend/app/services/catalog_loader.py` — portable catalog loader
  that reads `bi_meta.{metrics,dimensions,synonyms}` directly via
  SQLAlchemy on SQL Server, returning the same JSON shape the Python
  compiler already expects.
- `services/ask/runner._get_catalog_with_source` — dispatches to the
  new loader when `is_sqlserver()`; the PostgreSQL path is unchanged.
- `services/semantic/compiler` — the existing logic already lets
  T-SQL expressions (e.g. `DATEPART`) flow through on SQL Server; the
  scripts seed the catalog with such expressions so date-bucket
  dimensions work end-to-end on SQL Server.
- `backend/.env.example` — documents the local SQL Server URL.

## Remaining SQL Server adoption work after Phase C5

- SQL Server-first README and final operator runbook.
- Cleanup of temporary migration files and old branches after merge.
- Keep PostgreSQL as a temporary fallback until final approval.
- Migrate `services/query_service.py` off `utils/sql_safety.py`
  (still deferred from Phase B).
- Optional: ship `db/sqlserver/` views to mirror the remaining
  `bi.vw_*` analytical views that the project provides on PG.
