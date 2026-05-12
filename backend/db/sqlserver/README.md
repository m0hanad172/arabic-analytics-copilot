# SQL Server schema scripts (Phase C3)

Idempotent T-SQL scripts that stand up the `ArabicAnalytics` database
on Microsoft SQL Server so the Arabic Analytics Copilot backend can run
with `DATABASE_BACKEND=sqlserver` and `COMPILER_BACKEND=python`.

## Apply order (run in SSMS or `sqlcmd`)

```text
001_create_database.sql        -- creates ArabicAnalytics if missing
002_create_schemas.sql         -- creates bi, bi_meta if missing
003_create_bi_objects.sql      -- bi.fact_sales_line + bi.vw_fact_sales_line_clean
004_create_bi_meta_objects.sql -- bi_meta.metrics/dimensions/synonyms/plan_cache/query_log
005_seed_bi_meta.sql           -- 13 metrics + 13 dimensions + 54 synonyms (T-SQL flavour)
```

Each script can be re-run safely (`IF NOT EXISTS`, `MERGE` upserts,
predicated `CREATE TABLE`s).

## SSMS (Object Explorer)

1. Connect to `MOHANADLENOVO\SQLEXPRESS` with Windows authentication.
2. Open each `.sql` file (File → Open → File…) and press F5 in order.

## `sqlcmd` (terminal)

```powershell
sqlcmd -S MOHANADLENOVO\SQLEXPRESS -E -i .\backend\db\sqlserver\001_create_database.sql
sqlcmd -S MOHANADLENOVO\SQLEXPRESS -E -d ArabicAnalytics -i .\backend\db\sqlserver\002_create_schemas.sql
sqlcmd -S MOHANADLENOVO\SQLEXPRESS -E -d ArabicAnalytics -i .\backend\db\sqlserver\003_create_bi_objects.sql
sqlcmd -S MOHANADLENOVO\SQLEXPRESS -E -d ArabicAnalytics -i .\backend\db\sqlserver\004_create_bi_meta_objects.sql
sqlcmd -S MOHANADLENOVO\SQLEXPRESS -E -d ArabicAnalytics -i .\backend\db\sqlserver\005_seed_bi_meta.sql
```

## What is *not* in these scripts

- **Data load.** `bi.fact_sales_line` is created empty. Load the rows
  from `data/clean/bi_ready_clean.csv` with SSMS *Import Flat File…* or
  `bcp`. Phase C4 may ship a dedicated loader.
- **`plan_cache` upsert / `query_log` insert from /ask.** Tables are
  created here; the portable upsert/insert lands in Phase C4.
- **Mirror analytics views** (`vw_sales_by_*`, `vw_sales_monthly`,
  `vw_shipping_kpis`). `/ask` does not need them; Phase C4 can port
  them if/when a route consumes them.

## Type mapping

| PostgreSQL | T-SQL |
|---|---|
| `text` | `NVARCHAR(400)` (or `NVARCHAR(MAX)` for very long fields) |
| `integer` | `INT` |
| `bigint` | `BIGINT` |
| `numeric` (unspecified) | `DECIMAL(38, 6)` |
| `date` | `DATE` |
| `timestamptz` | `DATETIMEOFFSET` |
| `jsonb` | `NVARCHAR(MAX)` (Phase C4 may switch to native `JSON` on SQL Server 2022) |
| `boolean` | `BIT` |
