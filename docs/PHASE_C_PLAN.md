# Phase C Plan

The objective of Phase C is to remove the project's dependency on
PostgreSQL-resident logic (`bi_meta.*` PL/pgSQL functions) so the same
backend can serve Microsoft SQL Server. The chosen path is a **Python
semantic compiler** layered on top of the Phase A `SqlDialect` interface
and the Phase B DB adapter.

## Why Python compiler instead of T-SQL port

| Option | Pros | Cons | Verdict |
|---|---|---|---|
| Port `bi_meta.compile_query` PL/pgSQL → T-SQL | Closest to current architecture; minimal Python changes. | Two divergent codebases for the same logic; T-SQL has weaker string-handling primitives; every catalog/metric/filter change must be made twice; we still need Python parity for tests. | **No.** |
| Move compilation into Python (the chosen path) | Single source of truth; database holds only data; trivially extensible to other backends; testable without a database. | One-time effort to port the PL/pgSQL semantics; introduces a small Python module. | **Yes.** |

## Sub-phases

### C1 — Compiler foundation (this phase)

- Audit and export the bi_meta surface (done — `docs/BI_META_AUDIT.md`).
- New package `backend/app/services/semantic/` with:
  - `models.py` — typed plan / catalog / sort / filter dataclasses.
  - `errors.py` — clear compiler exceptions.
  - `catalog.py` — load a `Catalog` from the existing
    `bi_meta.get_catalog()` JSON shape (or any equivalent dict).
  - `compiler.py` — `compile_plan(plan, catalog, dialect=None) -> str`,
    no DB connections inside.
- Subset supported: `SELECT metrics`, `SELECT dimensions`, `FROM
  bi.vw_fact_sales_line_clean f`, `GROUP BY dimensions`, `ORDER BY
  metric/dimension`, `LIMIT/TOP` via `dialect.apply_limit()`,
  basic filters (`=`, `!=`, `<`, `<=`, `>`, `>=`, `ilike`, `between`,
  `in`), `order_count`, `net_sales`, sales/profit/discount metrics, and
  the dimensions `city`, `state`, `product_category`, `product_name`,
  `customer_type`, `account_manager`, `ship_mode`, `order_priority`,
  `order_date`. Date-bucket dimensions (`order_year`, `order_quarter`,
  `order_month`, `month_start`) work on PostgreSQL and raise
  `UnsupportedDimensionForBackend` on SQL Server pending Phase C2's
  T-SQL date expressions.
- New env flag `COMPILER_BACKEND` (default `db`). Allowed values:
  - `db` — current behaviour: `bi_meta.compile_query` (Postgres-only).
  - `python` — new compiler.
- `/ask` integration is **not** flipped in C1. Compiler is exercised
  only through unit tests.

### C2 status: completed

See `docs/DATABASE_MIGRATION.md → "Phase C2 Result"` for the full
list of changes. Highlights:

- `/ask` now dispatches between `bi_meta.compile_query` and the C1
  Python compiler via the `COMPILER_BACKEND` flag (default `db`).
- A new dialect-aware executor (`backend/app/db/adapter.fetch_select`)
  routes execution through asyncpg on PG and SQLAlchemy on SQL Server.
- Phase B's blanket SQL Server 501 is now scoped to the `db` compiler
  path. `DATABASE_BACKEND=sqlserver` + `COMPILER_BACKEND=python` runs
  end-to-end without asyncpg.
- PG-only `plan_cache`/`query_log` writes are skipped on SQL Server
  and listed in `meta.skipped_for_sqlserver`.
- Existing C1 contract preserved: date-bucket dimensions
  (`order_year`, `order_quarter`, `order_month`, `month_start`) raise
  `UnsupportedDimensionForBackend` on SQL Server until T-SQL date
  expressions are added.

### C2 — Wire-up and parity (original brief, now executed)

- Connect `runner.py`'s plan-compile step to the Python compiler when
  `COMPILER_BACKEND=python`. Keep the DB path as fallback.
- Implement the date-bucket dimensions with T-SQL expressions in the
  Python compiler.
- Replace the `bi_meta.plan_cache` upsert and `bi_meta.query_log`
  insert with portable SQL routed via the dialect (Postgres uses
  `INSERT ... ON CONFLICT`, SQL Server uses `MERGE` or check-then-insert).
- Migrate the catalog loader to read directly from
  `bi_meta.metrics` / `bi_meta.dimensions` / `bi_meta.synonyms` rather
  than the `get_catalog()` function, so SQL Server installations only
  need the tables (not the function).
- Live SQL Server smoke test: boot
  `mcr.microsoft.com/mssql/server:2022`, point `DATABASE_URL` at it,
  exercise `/health`, `/schema`, `/query`, `/ask` (with
  `COMPILER_BACKEND=python`).
- Migrate `services/query_service.py` off `utils/sql_safety.py`
  (deferred from Phase B).

### C3 status: completed

Phase C3 shipped the SQL Server schema/seed scripts under
`backend/db/sqlserver/`, the portable catalog loader at
`backend/app/services/catalog_loader.py`, and wired the runner to use
that loader on SQL Server. T-SQL date expressions
(`DATEPART(...)`, `DATEFROMPARTS(...)`) are seeded into
`bi_meta.dimensions` so date-bucket dimensions now compile on SQL
Server. See `docs/SQLSERVER_MIGRATION_PLAN.md` and the *Phase C3
Result* section of `docs/DATABASE_MIGRATION.md` for details.

### C4 — Cache/log + live SQL Server validation (next, awaits go)

- Portable `plan_cache` upsert (`MERGE` / `ON CONFLICT`) and
  `query_log` insert via the dialect, so the
  `meta.skipped_for_sqlserver` flags from Phase C2 finally clear.
- Data-load script for `bi.fact_sales_line` (CSV → SQL Server).
- Live smoke test against `MOHANADLENOVO\SQLEXPRESS` (or a
  containerised mssql).
- Migrate `services/query_service.py` off `utils/sql_safety.py`.

### C5 — Cleanup and adoption

- Default `COMPILER_BACKEND=python`.
- Optionally retire `bi_meta.compile_query` and `bi_meta.run_query` for
  new deployments (existing PostgreSQL deployments keep them as
  long-term backwards compatibility).
- Cleanup pass per `docs/CLEANUP_REPORT.md`.

## Risk register

- **Catalog drift.** If the bi_meta tables change shape, the Python
  compiler must be updated alongside. Phase C2 adds an integration test
  that runs both compilers against a known-plan catalog and compares
  output.
- **Filter parity.** PL/pgSQL's `quote_literal` is conservative;
  Python's literal escaping must avoid SQL injection. The Python
  compiler always escapes single quotes by doubling them — never via
  string interpolation of untrusted text into the WHERE expression.
- **Date dimensions.** `extract`, `date_trunc` have no exact T-SQL
  equivalent. Phase C2 adds the dialect-specific date expressions; C1
  refuses to compile these on SQL Server with a clear error.

## Out of scope for Phase C

- Frontend changes.
- Adding metrics or dimensions that bi_meta does not already define.
- Changing the API response shape.
- Re-implementing the LLM/Gemini path.
