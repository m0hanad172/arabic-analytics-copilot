# bi_meta Audit (Phase C1)

Read-only introspection of the live PostgreSQL database
`arabic_analytics` on `127.0.0.1:5432`, captured for Phase C1.

A full dump of the introspection output lives at `docs/.bi_meta_dump.txt`
and `docs/.bi_meta_data.txt` (gitignored — regenerate via
`python -m backend.tests._audit_bi_meta` with `DATABASE_URL` set).

## Schema overview

### Tables

| Table | Purpose | PG-specific bits |
|---|---|---|
| `bi_meta.dimensions` | Dimension catalog (`dim_key`, `display_name_ar/en`, `sql_expression`, `data_type`, `allowed_grouping`). 13 rows. | None — pure metadata. |
| `bi_meta.metrics` | Metric catalog (`metric_key`, `display_name_ar/en`, `agg`, `sql_expression`, `data_type`, `format_hint`). 13 rows. | The `sql_expression` values use PG syntax (`::numeric`, `::bigint`, `count(*)::bigint`). |
| `bi_meta.synonyms` | Arabic/English term → metric/dimension key. 54 rows. | None. |
| `bi_meta.plan_cache` | Cached LLM/rule plans keyed by `(question_norm, catalog_hash)`; uses `jsonb` for `plan`. | `jsonb` column type. |
| `bi_meta.query_log` | Per-request log: question, plan, sql, row count, warnings, suggestions, duration, cache/llm flags. | `jsonb` columns. |

### Views

| View | Purpose |
|---|---|
| `bi_meta.vw_plan_cache_recent` | 200-row recency window over `plan_cache`. |
| `bi_meta.vw_plan_cache_stats` | Aggregate counters over `plan_cache`. |
| `bi_meta.vw_query_log_recent` | 200-row recency window over `query_log`. |

### Functions

| Function | Language | Returns | Purpose |
|---|---|---|---|
| `bi_meta.get_catalog()` | sql | `jsonb` | Thin wrapper that delegates to `get_catalog('bi')`. |
| `bi_meta.get_catalog(p_schema text)` | sql | `jsonb` | Builds a JSON catalog object: `{ schema, base_view, metrics, dimensions, synonyms }`. Pure metadata read; no PG-specific logic in the **shape** of the result. |
| `bi_meta.compile_query(plan jsonb)` | plpgsql | `text` | Compiles a plan dict into a single `SELECT ... FROM bi.vw_fact_sales_line_clean f WHERE 1=1 [...] GROUP BY ... ORDER BY ... LIMIT n;` statement. Heavy use of `quote_literal`/`format('%I')`/`jsonb_array_elements*` and emits PG-specific operators (`ILIKE`, `::numeric`, `::bigint`). |
| `bi_meta.run_query(plan jsonb)` | plpgsql | `jsonb` | Calls `compile_query`, asserts the result starts with `SELECT`, executes via `EXECUTE format(...)` and aggregates rows with `jsonb_agg`. |

## What lives in PostgreSQL today

1. **Catalog metadata** — three rows-only tables (`metrics`, `dimensions`, `synonyms`) plus a JSON serializer (`get_catalog`). The shape of the output JSON is database-agnostic.
2. **SQL compilation** — `compile_query` builds a SELECT statement from the plan, joining metric/dimension keys to their stored `sql_expression`. Logic itself is portable; the output SQL it emits is **PostgreSQL-flavoured** (uses `ILIKE`, depends on the `::numeric`/`::bigint` casts that already live inside the catalog rows, ends with `LIMIT n;`).
3. **Cache + log persistence** — `plan_cache` upsert (`ON CONFLICT`) and `query_log` insert. Uses `jsonb`, `now()`, and PG-specific upsert syntax.
4. **Execution helper** — `run_query` is a thin wrapper that `EXECUTE`s the compiled SQL and `jsonb_agg`s the rows. Trivial logic.

## What should move to Python

| Concern | Move to Python? | Why |
|---|---|---|
| Catalog metadata (rows in `metrics`/`dimensions`/`synonyms`) | Stays in DB (read-only metadata). | Tabular reference data; portable to any backend without change. Loaded by Python via a simple `SELECT *` (no `bi_meta.*` function needed). |
| `get_catalog()` JSON serialization | **Move to Python.** | The JSON shape is database-agnostic. Building it in Python removes a `bi_meta.*` dependency and works on SQL Server unchanged. |
| `compile_query()` plan-to-SQL | **Move to Python.** | This is the central reason for Phase C. A Python compiler can emit dialect-specific SQL via the Phase A `SqlDialect` layer without forking PL/pgSQL into T-SQL. |
| `run_query()` SQL execution | **Move to Python.** | One-liner: execute the compiled SQL via SQLAlchemy / asyncpg and serialize rows. Already what Python has to do for SQL Server anyway. |
| `plan_cache` / `query_log` persistence | Phase C2 — keep DB tables, replace upsert/insert with portable SQL. | The schema is portable; the upsert syntax is not. SQL Server uses `MERGE` or check-and-insert. |

## What is just metadata access

Everything backed by `metrics`, `dimensions`, `synonyms`. These are
plain SELECTs against three small reference tables. Phase C1's catalog
loader uses one of:

- `bi_meta.get_catalog()` (current path; preserves backward
  compatibility for Postgres deployments that still rely on the
  function), or
- a direct portable `SELECT metric_key, agg, sql_expression, ... FROM
  bi_meta.metrics` (Phase C2 will adopt this for SQL Server).

## What is SQL compilation

`bi_meta.compile_query(plan)` does roughly the following pseudocode:

```text
limit = clamp(plan.limit, 1, 5000, default=500)
for d in plan.dimensions:
    expr = bi_meta.dimensions[d].sql_expression  # e.g. f.city
    select_dims += "{expr} AS {d}"
    group_by += expr
for m in plan.metrics:
    expr = bi_meta.metrics[m].sql_expression  # e.g. sum(f.order_total::numeric)
    select_mets += "{expr} AS {m}"
where = "1=1"
for f in plan.filters:
    expr = bi_meta.dimensions[f.field].sql_expression
    apply f.op (=, !=, >, >=, <, <=, ilike, between, in)
order = first plan.sort entry: ORDER BY "{field}" {asc|desc}
return "SELECT {dims}, {mets} FROM bi.vw_fact_sales_line_clean f WHERE {where} GROUP BY {gb} {order} LIMIT {n};"
```

The Python compiler in Phase C1 implements this verbatim, and uses
`SqlDialect.bigint_count()`, `cast_numeric()`, `ilike()`, and
`apply_limit()` so that the output is dialect-correct.

## What is cache/log persistence

`bi_meta.plan_cache` and `bi_meta.query_log`. Persistence happens
**outside** of `compile_query` — the runner reads the cache before
compilation and writes the log after execution. Phase C2 owns this
migration.

## PostgreSQL-specific syntax that must disappear for SQL Server

From the audited bi_meta surface:

| Construct | Where | SQL Server replacement |
|---|---|---|
| `::numeric` / `::bigint` | `bi_meta.metrics.sql_expression`, `bi_meta.dimensions.sql_expression`, `compile_query` output | `CAST(... AS NUMERIC(38,6))` / `COUNT_BIG(*)` (already supplied by `SqlDialect`). |
| `ILIKE` | `compile_query` filter branch | `LIKE` (SQL Server LIKE is case-insensitive under default CI collation; `SqlDialect.ilike()` already returns `LIKE`). |
| `LIMIT n` | `compile_query` tail | `SELECT TOP (n) ...` (`SqlDialect.apply_limit()`). |
| `extract(year from f.order_date_d)::int`, `date_trunc('month', f.order_date_d)::date` | `bi_meta.dimensions.sql_expression` for `order_year`, `order_quarter`, `order_month`, `month_start` | `DATEPART(year, f.order_date_d)`, `DATEFROMPARTS(YEAR(...), MONTH(...), 1)` etc. **Out of Phase C1 scope** — these dimensions are flagged as PG-only by the Python compiler until Phase C2 adds T-SQL equivalents to the catalog. |
| `format('%I')` / `quote_literal()` | `compile_query` PL/pgSQL helpers | Python compiler does its own identifier quoting (via `dialect.quote_ident()`) and parameterises literals safely. |
| `ON CONFLICT ... DO UPDATE` (plan_cache upsert) | `services/ask/cache.py` against `bi_meta.plan_cache` | `MERGE` or check-then-insert. **Phase C2.** |
| `jsonb` column types | `plan_cache.plan`, `query_log.plan/warnings/suggestions` | `NVARCHAR(MAX)` with JSON, or `JSON` data type if SQL Server 2022 native JSON is acceptable. **Phase C2.** |
| `now()` | `plan_cache` / `query_log` defaults and upsert | `SYSUTCDATETIME()` (`SqlDialect.now()`). **Phase C2.** |

## Phase C1 scope reminder

- We export and document everything here.
- We add a Python compiler that targets the same metric/dimension keys
  the bi_meta catalog already exposes.
- We **do not** drop, alter, or replace any `bi_meta.*` object.
- We **do not** flip `/ask` to the new compiler by default. The new
  setting `COMPILER_BACKEND` exists with default `db`; flipping it to
  `python` is a Phase C2 task and requires the parity battery in
  Phase C2 to pass first.
