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
