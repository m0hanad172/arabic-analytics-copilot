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

## Phase B (next — do not start without explicit confirmation)

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
