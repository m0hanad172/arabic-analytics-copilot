# SQL Server Acceptance Tests

## Purpose

This document defines the final SQL Server production-readiness checks for
Arabic Analytics Copilot. The goal is to prove that the company runtime uses
SQL Server end to end for catalog loading, Python compilation, guarded T-SQL,
plan cache, query logging, backend API responses, and frontend-visible results.

## SQL Server Runtime Assumptions

- SQL Server instance: `.\SQLEXPRESS`
- Database: `ArabicAnalytics`
- Runtime data table: `bi.fact_sales_line`
- Expected row count: `5000`
- Backend mode: `DATABASE_BACKEND=sqlserver`
- Compiler mode: `COMPILER_BACKEND=python`
- Driver: `ODBC Driver 18 for SQL Server`
- Authentication: Windows Authentication or SQL Authentication via local
  `MSSQL_USER` and `MSSQL_PASSWORD`

Do not commit local passwords. Keep real credentials in the local shell or
ignored `backend/.env` only.

## Backend Command

```powershell
$env:DATABASE_BACKEND="sqlserver"
$env:COMPILER_BACKEND="python"
$env:MSSQL_SERVER=".\SQLEXPRESS"
$env:MSSQL_DRIVER="ODBC Driver 18 for SQL Server"
$env:MSSQL_DATABASE="ArabicAnalytics"
$env:PYTHONIOENCODING="utf-8"

.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --reload --port 8000
```

If using SQL Authentication, also set these locally:

```powershell
$env:MSSQL_USER="<sql_login>"
$env:MSSQL_PASSWORD="<sql_password>"
```

## Frontend Command

```powershell
cd frontend
npm install
npm run dev
```

Open:

- http://localhost:3000

## SQL Server Verification Queries

Run in SSMS before the acceptance pass:

```sql
SELECT @@SERVERNAME AS server_name;
SELECT COUNT(*) AS rows_dbo_staging FROM dbo.bi_ready_clean;
SELECT COUNT(*) AS rows_fact FROM bi.fact_sales_line;
SELECT COUNT(*) AS cached_plans FROM bi_meta.plan_cache;
SELECT COUNT(*) AS query_logs FROM bi_meta.query_log;
```

Expected:

- `bi.fact_sales_line = 5000`
- `dbo.bi_ready_clean = 5000` when the staging table is retained
- `bi_meta.plan_cache` and `bi_meta.query_log` are present

## Cache Stabilization

Planner/compiler behavior is namespaced by `PLAN_CACHE_VERSION`. Old
`bi_meta.plan_cache` rows remain in the database but are not reused after the
version changes.

To clear stale SQL Server plan cache manually:

```sql
DELETE FROM bi_meta.plan_cache;
```

Do not clear `bi_meta.query_log`; it is operational history.

## Automated Acceptance Script

Run the optional live acceptance script:

```powershell
$env:PYTHONIOENCODING="utf-8"
python scripts/acceptance_sqlserver_questions.py
```

The script runs in-process with FastAPI `TestClient`, reads `MSSQL_*` from the
environment, never prints raw passwords, and verifies SQL Server syntax rules.
It runs questions 1-7 with `use_llm=0` for deterministic rule-based coverage,
and question 8 with `use_llm=1` to match the product UI path when LLM is
enabled. Question 8 still has rule-based/post-plan safeguards for limit, year,
city, and sort correctness.

## Acceptance Question List

1. اعرض عدد الطلبات حسب المدينة واعرض أعلى 5
2. اعرض المبيعات حسب السنة
3. اعرض الربح حسب فئة المنتج
4. اعرض أعلى 10 منتجات حسب المبيعات
5. اعرض الخصومات حسب فئة المنتج
6. اعرض المبيعات حسب الولاية
7. اعرض عدد الطلبات حسب نوع العميل
8. اعرض صافي المبيعات والربح الإجمالي وإجمالي الخصومات وعدد الطلبات حسب اسم المنتج والربع من مدينة سيدني خلال سنة 2015، ورتب النتائج حسب الربح الإجمالي تنازلياً واعرض أول 8 صفوف فقط

## Expected Checks For Every Question

- HTTP 200 from `/api/ask`
- `meta.compiler_backend = "python"`
- `meta.catalog_source = "sqlserver_tables"`
- `meta.skipped_for_sqlserver = null`
- `meta.log_id` is present
- generated SQL uses SQL Server syntax
- no `LIMIT`
- no `::bigint`
- no `::numeric`
- no `ILIKE`
- no `jsonb`
- no `AND AND`
- no `WHERE AND`
- no `OR OR`
- no `WHERE OR`

## Complex Question SQL Checks

For question 8, verify:

- `TOP (8)`
- `f.city IN ('Sydney')` or `f.city = 'Sydney'`
- `DATEPART(year, f.order_date_d) IN (2015)` or `DATEPART(year, f.order_date_d) = 2015`
- `gross_profit` included
- `discount_amount` included
- `order_count` included
- `ORDER BY [gross_profit] DESC`
- no `AND AND`
- no `LIMIT`
- no `::bigint`
- no `::numeric`
- no `ILIKE`
- no `jsonb`

## Customer Type Question SQL Checks

For question 7, verify:

- `f.customer_type AS [customer_type]`
- `COUNT_BIG(*) AS [order_count]`
- `GROUP BY f.customer_type`

## Manual Frontend Pass

In the frontend, submit each acceptance question and confirm:

- response table renders
- SQL panel shows T-SQL, not PostgreSQL syntax
- metadata shows SQL Server/python path
- complex query orders by gross profit descending
- repeated simple question can use cache

## Pass Criteria

The release is accepted when:

- SQL Server probe passes
- SQL Server smoke passes
- optional acceptance script passes
- focused backend tests pass
- no secrets are present in tracked files
- PostgreSQL/Docker fallback remains available but is not the production path
