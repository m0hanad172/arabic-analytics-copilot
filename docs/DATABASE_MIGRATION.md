# Database Migration: PostgreSQL → SQL Server

This document tracks the multi-phase migration from PostgreSQL to
Microsoft SQL Server. **Phase A** introduces the dialect foundation
only. Phase B handles the driver and connection abstraction; Phase C
handles `bi_meta.*` parity.

## Current state (after Phase A)

- **PostgreSQL is still the working backend.** No production behaviour
  changes when `DATABASE_BACKEND=postgres` (the default).
- New dialect layer at `backend/app/db/dialects/`:
  - `base.py` — abstract `SqlDialect` interface + `get_dialect()` resolver.
  - `postgres.py` — emits the SQL fragments the project uses today.
  - `sqlserver.py` — emits T-SQL-compatible fragments.
- `backend/app/sqlgen/translate.py` (now `v2.11-dialect-ordercount`)
  delegates `COUNT(*)::bigint`, `SUM(x)::numeric`, `NULLS LAST`, and the
  trailing row-cap to the active dialect. With the Postgres dialect the
  output is functionally identical to before; with the SQL Server
  dialect it produces `TOP (n)`, `COUNT_BIG(*)`,
  `CAST(... AS NUMERIC(38,6))`, and contains no `LIMIT` / `ILIKE` /
  `::bigint`.
- `backend/app/core/sql_guardrails.py` is now dialect-aware:
  - Allows `SELECT TOP (n) ...` (it already passes the SELECT-prefix check).
  - Adds T-SQL-dangerous tokens to the deny lists (`EXEC`, `MERGE`,
    `BACKUP`, `xp_cmdshell`, `OPENROWSET`, etc.) without weakening the
    PostgreSQL deny set.
  - Blocks SQL Server system schemas (`sys`, `master`, `msdb`, `tempdb`,
    `model`) in addition to the existing `pg_catalog`/`information_schema`/`pg_toast`.
  - Row-cap enforcement now uses `dialect.apply_limit(...)` so
    PostgreSQL queries keep `LIMIT n` and SQL Server queries get
    `TOP (n)`. Output is guaranteed to end with exactly one trailing
    semicolon when the guardrail had to inject the cap.
- New environment variable `DATABASE_BACKEND` (default `postgres`) in
  `backend/app/core/config.py` and `backend/.env.example`.

## What is intentionally **not** done in Phase A

- `/ask` is not migrated. `backend/app/api/routes/ask.py` still talks
  to PostgreSQL via `asyncpg` and calls Postgres-resident stored
  functions (`bi_meta.compile_query`, `bi_meta.get_catalog`,
  `bi_meta.plan_cache`, `bi_meta.query_log`). The SQL source for these
  functions is **not in this repo path**; we do not guess a T-SQL port.
- `backend/app/db/session.py` still constructs a Postgres async engine.
- `backend/app/services/query_service.py` still uses the older
  `utils/sql_safety.py` and a Postgres-only `SET statement_timeout`.
- `backend/app/utils/sql_safety.py` is left in place to avoid breaking
  callers; replacing it is a Phase B task.
- The `frontend/` React app is untouched.
- No files were deleted, moved, or archived.

## Phase B Audit: DB Access Surface

Captured on the `sqlserver-phase-b-db-access-abstraction` branch before
Phase B changes were applied.

| Area | Location | Notes |
|---|---|---|
| `asyncpg` direct use | `backend/app/services/ask/runner.py` (`_db_fetchval` / `_db_fetchrow` / `_db_fetch`, `_asyncpg_dsn`) | Opens a fresh connection per call, sets `SET statement_timeout = N`, runs the query, closes. Imported by `eval.py` (`from ...runner import _db_fetchval`) and re-exported by `services/ask/db.py`. |
| `asyncpg` indirect use | `backend/app/services/ask/cache.py` | Receives `db_fetchrow` / `db_fetchval` callables from `runner.py`; no asyncpg import of its own. |
| `AsyncSession` (SQLAlchemy) | `backend/app/db/session.py`, `backend/app/db/introspect.py`, `backend/app/services/catalog_cache.py`, `backend/app/services/query_service.py`, `backend/app/api/routes/{schema,query,logs}.py` | Driver-agnostic at the SQLAlchemy layer; the engine URL is the only PG coupling. |
| Raw `DATABASE_URL` reads | `backend/app/services/ask/runner.py:50`, `backend/app/main.py:8,27` (env loading) | Runner read kept for the asyncpg DSN. |
| PostgreSQL `$1`/`$2` placeholders | `services/ask/cache.py`, `services/ask/runner.py` (`bi_meta.*` calls), `api/routes/eval.py` (`bi_meta.run_query($1::jsonb)`), `services/catalog_cache.py` | All belong to the bi_meta path — owned by Phase C. |
| `::jsonb` casts | `services/ask/cache.py`, `services/ask/runner.py`, `api/routes/eval.py`, `services/catalog_cache.py` | Same — bi_meta path. |
| `ON CONFLICT` | `services/ask/cache.py` (`bi_meta.plan_cache` upsert) | Same — bi_meta path. |
| `SET statement_timeout` | `services/ask/runner.py` (asyncpg helpers, now via adapter), `services/query_service.py` | The `query_service.py` use is now routed through `dialect.set_statement_timeout()`. |
| `bi_meta.*` references | `api/routes/{logs,eval}.py`; `services/ask/{runner,cache}.py`; `services/catalog_cache.py` | Phase C scope. |

## Phase B Result

What was abstracted:

- **New module `backend/app/db/adapter.py`** — single home for backend
  identification (`active_backend()`, `is_postgres()`, `is_sqlserver()`),
  URL helpers (`get_database_url()`, `normalize_database_url_for_asyncpg()`),
  shared row helpers (`normalize_value()`, `ensure_json_obj()`), the
  asyncpg-based `pg_fetchval/pg_fetchrow/pg_fetch` helpers, and a
  controlled `BackendNotSupportedError` plus a canonical
  `controlled_backend_error_message()` string.
- **`backend/app/services/ask/runner.py`** no longer imports `asyncpg`
  directly. The historical `_db_fetchval` / `_db_fetchrow` / `_db_fetch`
  / `_asyncpg_dsn` / `_ensure_json_obj` names remain (so
  `services/ask/db.py` and `api/routes/eval.py` stay untouched), but
  they now delegate to `backend/app/db/adapter`.
- **`backend/app/services/query_service.py`** routes its statement
  timeout through `dialect.set_statement_timeout()` — emits exactly the
  same `SET statement_timeout = N` string on PostgreSQL, and skips the
  call cleanly on SQL Server. Row normalisation moved to
  `backend/app/db/adapter.normalize_value`; `_normalize_value` is kept
  as a backwards-compatible alias.
- **`backend/app/services/ask/runner.ask`** now short-circuits with a
  controlled `HTTPException(status_code=501, detail=…)` when
  `is_sqlserver()` is true, rather than letting asyncpg surface a
  driver-level error.

What still depends on PostgreSQL:

- The `bi_meta.*` SQL functions called by `runner.py`, `cache.py`,
  `eval.py`, `logs.py`, and `catalog_cache.py`. Their source is not in
  this repo, so we cannot safely port them yet.
- The asyncpg driver itself: `pg_fetchval/pg_fetchrow/pg_fetch` still
  open asyncpg connections. They are the only path to bi_meta and are
  guarded by `is_postgres()`.
- `db/session.py` still creates a single async engine from
  `DATABASE_URL`. SQLAlchemy's URL determines the driver, so pointing
  `DATABASE_URL` at `mssql+aioodbc://...` will create a SQL Server
  engine; only routes that touch bi_meta will then fail (controlled
  501).

Why SQL Server `/ask` still needs Phase C:

- `/ask` reads `bi_meta.get_catalog()`, writes
  `bi_meta.plan_cache`, calls `bi_meta.compile_query(jsonb)`, and logs
  to `bi_meta.query_log`. These are PL/pgSQL objects living inside
  PostgreSQL; we have no T-SQL equivalents and no source to port.
- Returning a controlled 501 is the safe compromise: SQL Server users
  see a clear blocker rather than a stack trace.

Exact next steps for Phase C:

1. Obtain or write the T-SQL definitions of `bi_meta.compile_query`,
   `bi_meta.get_catalog`, `bi_meta.plan_cache`, and `bi_meta.query_log`
   — or move plan compilation and the catalog/cache/log persistence
   into Python services.
2. Replace asyncpg-only paths in `services/ask/runner.py` with
   SQLAlchemy `AsyncSession` calls so the same code can talk to either
   backend.
3. Migrate `services/query_service.py` off `utils/sql_safety.py` to
   `core/sql_guardrails.guard_sql_or_raise` (deferred from Phase B to
   keep this change small; the active guardrail there is still the
   older one).
4. Add an integration smoke test that boots a SQL Server container
   (`mcr.microsoft.com/mssql/server:2022`), points `DATABASE_URL` at
   it, and exercises `/health`, `/schema`, `/query`, `/ask` (the last
   should return 501 until step 1 ships, then full pass).

## Phase C1 Result

**Goal:** stand up an in-process semantic compiler so Phase C2 can flip
`/ask` to it on SQL Server without porting `bi_meta.compile_query` to
T-SQL. PostgreSQL behaviour is untouched (default `COMPILER_BACKEND=db`).

### Why a Python compiler instead of a T-SQL port

See `docs/PHASE_C_PLAN.md` ("Why Python compiler instead of T-SQL port")
and `docs/BI_META_AUDIT.md` ("What should move to Python") — the short
version: a single Python implementation gives us one source of truth,
keeps the database to just data, and emits dialect-correct SQL via the
Phase A `SqlDialect` layer.

### What was added

- New configuration value `COMPILER_BACKEND` in
  `backend/app/core/config.py` (default `db`). Allowed values: `db` (use
  `bi_meta.compile_query` — current behaviour) and `python` (new
  in-process compiler). Documented in `backend/.env.example`.
- New package `backend/app/services/semantic/`:
  - `errors.py` — typed exceptions: `CompilerError`,
    `UnknownMetricError`, `UnknownDimensionError`,
    `UnsupportedFilterOpError`, `InvalidFilterValueError`,
    `EmptyPlanError`, `UnsupportedDimensionForBackend`.
  - `models.py` — frozen dataclasses for `Metric`, `Dimension`, `Plan`,
    `Filter`, `Sort`, plus `Plan.from_dict` for loose dict input.
  - `catalog.py` — `Catalog.from_bi_meta(...)` adapts the JSON shape
    produced by `bi_meta.get_catalog()` (or any equivalent dict).
  - `compiler.py` — `compile_plan(plan, catalog, dialect=None) -> str`,
    no DB connections inside; emits dialect-correct SQL with exactly
    one trailing semicolon.
- Documentation: `docs/BI_META_AUDIT.md` and `docs/PHASE_C_PLAN.md`.
- Read-only introspection helper `backend/tests/_audit_bi_meta.py`
  (used to capture the audit; not run by pytest).

### Live PostgreSQL audit summary

Captured against `arabic_analytics` on `127.0.0.1:5432`:

- **Tables:** `bi_meta.{dimensions, metrics, synonyms, plan_cache, query_log}` (54 synonyms; 13 metrics; 13 dimensions).
- **Views:** `bi_meta.{vw_plan_cache_recent, vw_plan_cache_stats, vw_query_log_recent}`.
- **Functions:** `bi_meta.get_catalog()` and `bi_meta.get_catalog(text)` (sql), `bi_meta.compile_query(jsonb)` and `bi_meta.run_query(jsonb)` (plpgsql).
- Full sources captured in `docs/BI_META_AUDIT.md` and `docs/.bi_meta_dump.txt`.

### Subset supported by the Phase C1 compiler

- `SELECT` of metrics + dimensions in plan order.
- `FROM bi.vw_fact_sales_line_clean f` (or whatever `base_view` the catalog declares).
- `WHERE 1=1` plus per-filter `AND ...` for `=`, `!=`, `>`, `>=`, `<`, `<=`, `ilike`, `between`, `in`. Empty `IN (...)` becomes `1=0` (mirrors PG).
- `GROUP BY <dim_expression, ...>`.
- `ORDER BY <field> <ASC|DESC>` (first sort entry that resolves to a known metric or dimension).
- Limit clamping `[1, 5000]`, default 500 (verbatim mirror of `bi_meta.compile_query`).
- Trailing row cap via `dialect.apply_limit` — `LIMIT n` on PostgreSQL, `TOP (n)` on SQL Server.
- Metrics: every metric currently in the live `bi_meta.metrics` table (`net_sales`, `gross_sales`, `discount_amount`, `discounts`, `gross_profit`, `cogs`, `line_count`, `order_count`, `avg_ship_delay_days`, `avg_discount_pct`, `profit_after_shipping`, `shipping_cost`, `units`).
- Dimensions on **PostgreSQL**: every dimension in the live catalog. On **SQL Server**: every dimension whose stored expression is portable (`f.<column>`). Date-bucket dimensions (`order_year`, `order_quarter`, `order_month`, `month_start`) are explicitly rejected with `UnsupportedDimensionForBackend` until Phase C2 adds T-SQL date expressions.

### What still depends on PostgreSQL

- `services/ask/runner.py` still uses asyncpg via the Phase B adapter
  for the bi_meta cache/log path. Not changed in C1.
- `services/ask/cache.py` still issues PostgreSQL `ON CONFLICT` SQL
  against `bi_meta.plan_cache`. Phase C2.
- `api/routes/eval.py`, `api/routes/logs.py` still call `bi_meta.*`
  directly. Phase C2 will route them through the Python compiler /
  portable SQL.
- `services/catalog_cache.py` still calls `bi_meta.get_catalog()` to
  load the JSON catalog. Phase C2 may replace with a direct
  `SELECT * FROM bi_meta.metrics/dimensions/synonyms`.
- The `bi_meta.compile_query` PostgreSQL function is still present in
  the database; we have not dropped it.

### Why SQL Server `/ask` still needs Phase C2

`/ask` reads/writes `bi_meta.plan_cache`, `bi_meta.query_log`, and
calls `bi_meta.compile_query`. Phase C1 only **adds** a Python
compiler; it does not flip `/ask` to use it. SQL Server `/ask` therefore
still returns the controlled HTTP 501 introduced in Phase B.

### Exact next steps for Phase C2

1. In `services/ask/runner.py`, when `COMPILER_BACKEND=python`:
   - Load the catalog via `Catalog.from_bi_meta(...)`.
   - Compile plans via `compile_plan(plan, catalog, dialect=get_dialect())`.
   - Skip the `bi_meta.compile_query` round-trip.
2. Replace `bi_meta.plan_cache` upsert (`ON CONFLICT`) with portable
   SQL via the dialect (`MERGE` / check-then-insert on SQL Server,
   keep `ON CONFLICT` on PostgreSQL).
3. Replace `bi_meta.query_log` insert with portable SQL.
4. Add T-SQL expressions for `order_year`, `order_quarter`,
   `order_month`, `month_start` to the Python compiler.
5. Migrate `services/catalog_cache.py` to read directly from
   `bi_meta.metrics` / `bi_meta.dimensions` / `bi_meta.synonyms` (no
   `get_catalog()` call required for SQL Server).
6. Live SQL Server smoke test: boot
   `mcr.microsoft.com/mssql/server:2022`, point `DATABASE_URL` at it,
   exercise `/health`, `/schema`, `/query`, `/ask` (now expected to
   succeed).

## Phase C2 Result

**Goal:** wire the Phase C1 Python compiler into `/ask` behind the
`COMPILER_BACKEND` flag. Default behaviour is unchanged.

### How to enable the Python compiler

```env
COMPILER_BACKEND=python
```

Default remains `COMPILER_BACKEND=db`.

### What was added

- New dispatcher [backend/app/services/ask/compile.py](backend/app/services/ask/compile.py):
  - `active_compiler_backend()` resolves the active value with a safe
    fallback to `db` on unknown values.
  - `compile_for_request(plan, catalog, *, dialect=None) -> (sql, used)`
    runs either `bi_meta.compile_query` (`db`) or the C1
    `compile_plan(...)` (`python`).
  - `db` path raises `BackendNotSupportedError` on SQL Server with a
    hint to switch to `COMPILER_BACKEND=python`.
- New executor in [backend/app/db/adapter.py](backend/app/db/adapter.py):
  - `fetch_select(sql)` — PostgreSQL uses asyncpg (`pg_fetch`); SQL
    Server uses SQLAlchemy `AsyncSession` via `db/session.py`. Rows are
    normalised through `normalize_value` for JSON serialisation.
- [backend/app/services/ask/runner.py](backend/app/services/ask/runner.py):
  - Phase B's blanket `if is_sqlserver(): 501` is now scoped: it only
    fires when `compiler_backend == "db"` (db compiler needs PG). The
    message is updated to hint at `COMPILER_BACKEND=python`.
  - `bi_meta.compile_query` call replaced with `compile_for_request(...)`.
  - Row execution replaced with `fetch_select(...)`.
  - PG-only cache reads (`_cache_get_plan`, `_cache_touch`) and writes
    (`_cache_upsert_plan`) gated on `is_postgres()`.
  - `bi_meta.query_log` insert gated on `is_postgres()`.
  - Response `meta` gains two fields:
    - `compiler_backend` — `"db"` or `"python"`.
    - `skipped_for_sqlserver` — list of PG-only side channels skipped
      (`plan_cache`, `query_log`) on SQL Server, or `None`.

### What still depends on PostgreSQL

- `services/catalog_cache.py` and `services/ask/runner._get_catalog_with_source`
  still call `bi_meta.get_catalog()`. SQL Server installations need a
  catalog loader that reads the `bi_meta.{metrics,dimensions,synonyms}`
  tables directly. Tests inject a catalog dict to exercise the
  SQL Server path; production SQL Server deployments will need either
  this loader or a one-off catalog seed.
- `bi_meta.plan_cache` upsert (`ON CONFLICT`) and `bi_meta.query_log`
  insert remain PG-only. On SQL Server they are skipped cleanly and
  the response's `meta.skipped_for_sqlserver` lists them.
- Date-bucket dimensions (`order_year`, `order_quarter`, `order_month`,
  `month_start`) still raise `UnsupportedDimensionForBackend` on SQL
  Server until T-SQL date expressions are added to the Python compiler.
- `services/ask/cache.py` and `api/routes/{eval,logs}.py` still issue
  PG-specific SQL against `bi_meta.*` tables.
- `services/query_service.py` still uses `utils/sql_safety.py` (the
  older guardrail). Migration to `core/sql_guardrails.guard_sql_or_raise`
  is deferred from Phase B; nothing depends on doing it before the
  SQL Server schema migration.

### What SQL Server can now do

With `DATABASE_BACKEND=sqlserver` and `COMPILER_BACKEND=python`:

- `/ask` no longer returns Phase B's blanket 501.
- The active dialect is SQL Server; the Python compiler emits T-SQL
  (`TOP (n)`, `COUNT_BIG(*)`, `CAST(... AS NUMERIC(38,6))`, `LIKE`).
- No asyncpg connection is opened; SQL goes through the SQLAlchemy
  `AsyncSession` (which loads the configured driver lazily).
- Guardrails still apply.
- `plan_cache` and `query_log` writes are skipped and surfaced in
  `meta.skipped_for_sqlserver`.

### What remains for SQL Server schema/data migration (Phase C3 candidates)

1. **Catalog loader**: read `bi_meta.metrics` / `bi_meta.dimensions` /
   `bi_meta.synonyms` directly via SQLAlchemy and build the JSON shape
   in Python — so SQL Server only needs the tables, not the
   `get_catalog()` function.
2. **Schema/data scripts for SQL Server**: ship `db/sqlserver/`
   migration scripts that create `bi.vw_fact_sales_line_clean`,
   `bi_meta.metrics`, `bi_meta.dimensions`, `bi_meta.synonyms`,
   `bi_meta.plan_cache`, `bi_meta.query_log` with T-SQL syntax.
3. **Portable plan_cache / query_log**: implement upsert/insert via
   the dialect (`INSERT ... ON CONFLICT` on PG, `MERGE` /
   check-then-insert on SQL Server).
4. **Date-bucket dimensions on T-SQL**: emit `DATEPART(year, ...)`,
   quarter / month start expressions in the Python compiler.
5. **Live SQL Server smoke test**: boot
   `mcr.microsoft.com/mssql/server:2022`, point `DATABASE_URL` at it,
   and exercise `/health`, `/schema`, `/query`, `/ask` end-to-end.
6. **`services/query_service.py`** off `utils/sql_safety.py` (deferred
   from Phase B).

## Phase C3 Result

**Goal:** ship SQL Server schema/seed scripts and a portable catalog
loader so `ArabicAnalytics` can run with
`DATABASE_BACKEND=sqlserver` + `COMPILER_BACKEND=python`. PostgreSQL
behaviour is preserved (default `DATABASE_BACKEND=postgres`,
`COMPILER_BACKEND=db`).

See [docs/SQLSERVER_MIGRATION_PLAN.md](SQLSERVER_MIGRATION_PLAN.md)
for the full audit, type-mapping table, and operator runbook.

### What was added

- **SQL Server schema/seed scripts** under
  [backend/db/sqlserver/](../backend/db/sqlserver/):
  - `001_create_database.sql` — creates `ArabicAnalytics` if absent.
  - `002_create_schemas.sql` — creates `bi` and `bi_meta` schemas.
  - `003_create_bi_objects.sql` — `bi.fact_sales_line` (28 columns,
    mirroring the PG base table) + `bi.vw_fact_sales_line_clean` view
    that aliases `order_date`/`ship_date` → `order_date_d`/`ship_date_d`
    so the catalog/compiler can reference them unchanged.
  - `004_create_bi_meta_objects.sql` — T-SQL versions of
    `bi_meta.metrics`, `bi_meta.dimensions`, `bi_meta.synonyms`,
    `bi_meta.plan_cache` (with unique index on `(question_norm, catalog_hash)`),
    and `bi_meta.query_log` (jsonb → `NVARCHAR(MAX)`, defaults via
    `SYSUTCDATETIME()`).
  - `005_seed_bi_meta.sql` — idempotent `MERGE` upserts for the 13
    metrics, 13 dimensions, and 54 synonyms exported from live PG,
    translated to T-SQL (`COUNT_BIG(*)`, `DATEPART(...)`,
    `DATEFROMPARTS(...)`, no `::cast`).
  - `README.md` — SSMS + `sqlcmd` invocation order; what is *not*
    shipped (data load).
  - `_gen_seed.py` — generator used to produce `005_seed_bi_meta.sql`
    from `docs/.bi_meta_export.json`. Build helper only; not executed
    at runtime.
- **Portable catalog loader** [backend/app/services/catalog_loader.py](../backend/app/services/catalog_loader.py):
  - `load_sqlserver_catalog(schema)` — uses SQLAlchemy `AsyncSession`
    to read `bi_meta.{metrics,dimensions,synonyms}` directly and
    returns the same JSON shape as `bi_meta.get_catalog()`. No PG
    syntax used.
  - `load_catalog_for_active_backend(schema)` — dispatches to the
    SQL Server loader when `is_sqlserver()`, otherwise delegates to the
    pre-existing PG path (via `runner._db_fetchval`).
  - `_build_catalog_dict(...)` — pure assembly, factored out so unit
    tests do not need a SQLAlchemy session.
- **Runner wiring** in
  [services/ask/runner._get_catalog_with_source](../backend/app/services/ask/runner.py):
  on SQL Server, calls `load_sqlserver_catalog(schema)` and tags the
  catalog with `catalog_source="sqlserver_tables"`. PG path is
  unchanged.
- **`.env.example`** documents the exact local URL for
  `MOHANADLENOVO\SQLEXPRESS` with both Driver 17 and Driver 18
  alternatives, plus the `aioodbc` async variant.
- **Documentation**:
  - New `docs/SQLSERVER_MIGRATION_PLAN.md`.
  - This file gains a *Phase C3 Result* section.
  - `docs/PHASE_C_PLAN.md` marks C3 complete.

### Date-dimension support

The Python compiler's SQL Server path already lets through any
expression that does not use `extract(...)` or `date_trunc(...)`. The
Phase C3 seed therefore stores T-SQL date expressions
(`DATEPART(year, f.order_date_d)`,
`DATEFROMPARTS(YEAR(f.order_date_d), MONTH(f.order_date_d), 1)`) which
compile cleanly. PostgreSQL output is unchanged (its dialect branch
returns the catalog expression verbatim).

Regression covered by
[backend/tests/test_python_compiler.py:TestCompilerSqlServer.test_tsql_date_dimensions_pass_through](../backend/tests/test_python_compiler.py) — every C2 date dimension on PG now also works on SQL Server when seeded with T-SQL expressions.

### PostgreSQL behaviour preserved

- Default settings (`DATABASE_BACKEND=postgres`, `COMPILER_BACKEND=db`)
  produce the same SQL through the same code paths as before Phase C3.
- The catalog loader's PG branch still delegates to
  `runner._db_fetchval("SELECT bi_meta.get_catalog($1)::jsonb;", ...)`.
- Existing PG-backed tests (`test_golden`, `test_ask_standard`,
  `test_quality_xfail`) still pass.
- Full suite: 153 passed, 1 skipped, 1 xfailed (vs C2 baseline 135).

### What you need to run manually in SSMS to create ArabicAnalytics

```text
1. Connect to .\SQLEXPRESS (or the server shown by SSMS) with Windows
   authentication or SQL authentication.
2. Open and execute, in order:
     backend/db/sqlserver/001_create_database.sql
     backend/db/sqlserver/002_create_schemas.sql       (after switching to ArabicAnalytics)
     backend/db/sqlserver/003_create_bi_objects.sql
     backend/db/sqlserver/004_create_bi_meta_objects.sql
     backend/db/sqlserver/005_seed_bi_meta.sql
3. Load the fact table:
     - Right-click ArabicAnalytics > Tasks > Import Flat File ...
     - Source: data/clean/bi_ready_clean.csv (existing project export)
     - Destination: bi.fact_sales_line
   Or use bcp/SqlBulkCopy.
4. In a project venv:
     pip install aioodbc pyodbc
5. Set in backend/.env (NOT in .env.example):
     DATABASE_BACKEND=sqlserver
     COMPILER_BACKEND=python
     DATABASE_URL=mssql+aioodbc:///?odbc_connect=DRIVER%3D%7BODBC+Driver+18+for+SQL+Server%7D%3BSERVER%3D.%5CSQLEXPRESS%3BDATABASE%3DArabicAnalytics%3BTrusted_Connection%3Dyes%3BTrustServerCertificate%3Dyes%3BEncrypt%3Dno%3B
```

Use SQLAlchemy's `odbc_connect=` form for named instances. Do not use
the older `mssql+...://@.%5CSQLEXPRESS/...` netloc style.

### What remains for Phase C4

1. Portable `plan_cache` upsert via the dialect (`MERGE` on T-SQL,
   `INSERT ... ON CONFLICT` on PG) and the same for `query_log` insert
   — so caching/logging stop being skipped on SQL Server.
2. Data load script or documented `bcp`/SqlBulkCopy command for
   `bi.fact_sales_line` (still manual today).
3. Live SQL Server smoke test against `MOHANADLENOVO\SQLEXPRESS` (or a
   containerised `mcr.microsoft.com/mssql/server:2022`).
4. Migrate `services/query_service.py` off `utils/sql_safety.py`
   (deferred from Phase B).
5. Optional: port the remaining `bi.vw_*` analytical views
   (`vw_sales_by_*`, `vw_sales_monthly`, `vw_shipping_kpis`) so they
   are available on SQL Server too.

## Future phases (carried over from Phase A)

Driver and connection abstraction.

1. Make `db/session.py` choose an engine URL/driver per
   `DATABASE_BACKEND`. SQL Server uses a SQLAlchemy URL like
   `mssql+aioodbc://...`. Add the dependency only when adopted.
2. Replace `asyncpg` usage in `ask.py` with SQLAlchemy `text()` +
   `AsyncSession`, so the file becomes driver-agnostic.
3. Centralise statement-timeout handling through the dialect
   (`set_statement_timeout()` returns `None` on SQL Server, where the
   timeout is configured client-side).
4. Migrate `services/query_service.py` to use
   `core.sql_guardrails.guard_sql_or_raise` and remove
   `utils/sql_safety.py` (per the cleanup report).
5. Add an integration smoke test against a local SQL Server container.

## Phase C (after Phase B)

`bi_meta.*` parity. **Currently blocked** until either:

- (a) the existing PL/pgSQL source for `bi_meta.compile_query`,
  `bi_meta.get_catalog`, `bi_meta.plan_cache`, and `bi_meta.query_log`
  is added to this repo (e.g., under `db/` or `tools/db/`), **or**
- (b) we agree to reimplement plan compilation in Python so the
  database holds only data, not logic.

Once unblocked, port the `bi_meta.*` objects to T-SQL or move them into
Python services, then wire `/ask` through the dialect layer end-to-end.

## Environment variable reference

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_BACKEND` | `postgres` | Selects the active dialect. `postgres` or `sqlserver`. |
| `DATABASE_URL` | (required) | SQLAlchemy URL for the active backend. See `backend/.env.example`. |
| `ALLOWED_SCHEMA` | `bi` | Schema allowlist used by introspection. |
| `SQL_ALLOWED_SCHEMAS` | `bi` (or env) | Comma-separated allowlist used by guardrails. |
| `DEFAULT_MAX_ROWS` | `200` | Row cap applied when a query has no LIMIT/TOP. |
| `STATEMENT_TIMEOUT_MS` | `8000` | Per-statement timeout. Honoured on PostgreSQL only; ignored on SQL Server until Phase B wires a client-side equivalent. |

## How to run the test suite

```
pytest -q
```

Phase A's new tests cover:

- Dialect resolver and the contract for both backends
  (`backend/tests/test_dialects.py`).
- The translator under each dialect, asserting SQL Server output has
  no `::bigint`, `::numeric`, `LIMIT n`, or `ILIKE`
  (`backend/tests/test_translate_dialects.py`).
- The guardrails accepting safe SELECT shapes (including
  `SELECT TOP (n)`) while still blocking DDL/DML, `EXEC`, multi-statement
  payloads, comments, dangerous functions, and disallowed schemas
  (`backend/tests/test_guardrails_dialects.py`).

Some tests (`test_ask_standard.py`, `test_golden.py`,
`test_quality_xfail.py`) require a running PostgreSQL on
`localhost:5432`; they are unaffected by Phase A and continue to require
the same fixture.
