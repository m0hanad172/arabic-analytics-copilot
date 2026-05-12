# SQL Server Migration Plan

Phase C3 deliverable. This document describes how to stand up the
ArabicAnalytics database on Microsoft SQL Server, and what the Phase C3
code changes do.

## Target environment

| | |
|---|---|
| Server instance | `MOHANADLENOVO\SQLEXPRESS` |
| Database | `ArabicAnalytics` |
| Schemas | `bi`, `bi_meta` |
| Connection style | Windows trusted (integrated security) |
| ODBC driver | `ODBC Driver 17 for SQL Server` (preferred) or `ODBC Driver 18 for SQL Server` |

Example SQLAlchemy URL (used by `backend/.env.example`):

```env
DATABASE_BACKEND=sqlserver
COMPILER_BACKEND=python
DATABASE_URL=mssql+pyodbc://@MOHANADLENOVO%5CSQLEXPRESS/ArabicAnalytics?driver=ODBC+Driver+17+for+SQL+Server&trusted_connection=yes&TrustServerCertificate=yes
```

`%5C` is URL-encoded `\`. If you have Driver 18 installed, swap to
`driver=ODBC+Driver+18+for+SQL+Server`. Driver 18 enables encryption by
default; keep `TrustServerCertificate=yes` for a local dev box that has
no signed certificate.

The async path uses `aioodbc` (`mssql+aioodbc://...`). Phase C3 does
**not** add `aioodbc` as a hard dependency; install it locally before
exercising the live SQL Server runtime:

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
2. Connect to `MOHANADLENOVO\SQLEXPRESS` with Windows authentication.
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

6. Set the SQL Server URL in `backend/.env`:

   ```env
   DATABASE_BACKEND=sqlserver
   COMPILER_BACKEND=python
   DATABASE_URL=mssql+pyodbc://@MOHANADLENOVO%5CSQLEXPRESS/ArabicAnalytics?driver=ODBC+Driver+17+for+SQL+Server&trusted_connection=yes&TrustServerCertificate=yes
   ```

   Note: `backend/.env` is gitignored and **must not** be committed.
   Use `backend/.env.example` as the template only.

7. Boot the backend (`uvicorn ...`) and try `/ask` with a question
   that only uses supported metrics/dimensions. `plan_cache` /
   `query_log` writes are silently skipped on SQL Server until
   Phase C4 ships the portable upsert/insert.

## SQL Server Express connection troubleshooting (Phase C4 hotfix)

SSMS connecting fine while pyodbc fails almost always means a named-instance
discovery / protocol problem, not a credentials problem. Work through this
list before changing connection strings:

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

### 6. Probe scripts

```powershell
# Walk through driver/server combos and print the working one.
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

### 7. Connection-string patterns tried by the probe

In priority order (cheap/local first, then TCP fallbacks):

```
.\SQLEXPRESS
localhost\SQLEXPRESS
(local)\SQLEXPRESS
MOHANADLENOVO\SQLEXPRESS
lpc:.\SQLEXPRESS
np:\\.\pipe\MSSQL$SQLEXPRESS\sql\query
tcp:localhost,1433
tcp:127.0.0.1,1433
```

### 8. Moving staged rows into `bi.fact_sales_line`

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

## What still has to happen for full SQL Server `/ask` parity (Phase C4)

- Portable `plan_cache` upsert (`MERGE` on T-SQL, `INSERT ... ON CONFLICT`
  on PG) and `query_log` insert.
- Data load for `bi.fact_sales_line` (script or documented `bcp`).
- Live integration smoke test against `MOHANADLENOVO\SQLEXPRESS`.
- Migrate `services/query_service.py` off `utils/sql_safety.py`
  (still deferred from Phase B).
- Optional: ship `db/sqlserver/` views to mirror the remaining
  `bi.vw_*` analytical views that the project provides on PG.
