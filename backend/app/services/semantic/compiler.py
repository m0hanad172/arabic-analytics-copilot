"""Plan-to-SQL compiler (Phase C1).

A pure-Python re-implementation of ``bi_meta.compile_query`` that
emits dialect-aware SQL via the Phase A ``SqlDialect`` interface.

Contract:
- Accepts a ``plan`` (dict or :class:`Plan`), a :class:`Catalog`, and
  an optional dialect.
- Returns a single SQL ``str`` ending with exactly one ``;``.
- Never opens a database connection. Pure CPU.

Mirrors the PostgreSQL semantics of ``bi_meta.compile_query``:
- limit clamped to [1, 5000], default 500.
- ``SELECT <dim AS k, ...>, <metric AS k, ...>``
- ``FROM bi.vw_fact_sales_line_clean f``
- ``WHERE 1=1`` plus per-filter predicates joined by ``AND``.
- ``GROUP BY <dim_expr, ...>`` when there is at least one dimension.
- ``ORDER BY "<sort_field>" <dir>`` for the first sort entry that
  resolves to a known metric or dimension.
- Trailing row cap via ``dialect.apply_limit``.

PostgreSQL output is functionally equivalent to ``bi_meta.compile_query``
for the supported subset (see docs/PHASE_C_PLAN.md). SQL Server output
substitutes ``COUNT_BIG(*)``, ``CAST(... AS NUMERIC(38,6))``, ``LIKE``,
and ``TOP (n)`` so the result contains no ``::bigint`` / ``::numeric`` /
``ILIKE`` / trailing ``LIMIT``.
"""
from __future__ import annotations

import re
from typing import Any, Iterable, List, Optional, Union

from backend.app.db.dialects import SqlDialect, get_dialect

from .catalog import Catalog
from .errors import (
    EmptyPlanError,
    InvalidFilterValueError,
    UnknownDimensionError,
    UnknownMetricError,
    UnsupportedDimensionForBackend,
    UnsupportedFilterOpError,
)
from .models import Filter, Plan


# ---- limits ---------------------------------------------------------------
_DEFAULT_LIMIT = 500
_MIN_LIMIT = 1
_MAX_LIMIT = 5000

# ---- supported filter ops ------------------------------------------------
_COMPARISON_OPS = {"=", "!=", ">", ">=", "<", "<="}
_ALL_OPS = _COMPARISON_OPS | {"ilike", "between", "in"}


# ---- catalog-expression rewriting ----------------------------------------
_PG_NUMERIC_CAST = re.compile(r"::numeric\b", flags=re.IGNORECASE)
_PG_BIGINT_CAST = re.compile(r"::bigint\b", flags=re.IGNORECASE)
_PG_INT_CAST = re.compile(r"::int(?:eger)?\b", flags=re.IGNORECASE)
_PG_DATE_CAST = re.compile(r"::date\b", flags=re.IGNORECASE)
# These functions have no portable T-SQL equivalent in Phase C1.
_PG_DATE_FUNCS = re.compile(r"\b(date_trunc|extract)\s*\(", flags=re.IGNORECASE)
# count(*)::bigint or COUNT(*)::bigint -- catalog metric for line_count/order_count.
_COUNT_STAR = re.compile(r"\bcount\s*\(\s*\*\s*\)\s*(?:::bigint)?", flags=re.IGNORECASE)
_NUMERIC_AGG_INNER = re.compile(
    r"^(?P<fn>sum|avg|min|max)\s*\(\s*(?P<inner>.+?)(?:::numeric)?\s*\)\s*(?:::numeric)?$",
    flags=re.IGNORECASE | re.DOTALL,
)
_LEADING_BOOLEAN = re.compile(r"^\s*(?:AND|OR)\b\s*", flags=re.IGNORECASE)


def _strip_pg_casts(expr: str) -> str:
    out = _PG_NUMERIC_CAST.sub("", expr)
    out = _PG_BIGINT_CAST.sub("", out)
    out = _PG_INT_CAST.sub("", out)
    out = _PG_DATE_CAST.sub("", out)
    return out


def _quote_literal(v: Any) -> str:
    """Single-quote a SQL literal, doubling embedded single quotes."""
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, (int, float)):
        return str(v)
    s = str(v)
    return "'" + s.replace("'", "''") + "'"


# ---- public API -----------------------------------------------------------
def compile_plan(
    plan: Union[Plan, dict],
    catalog: Catalog,
    dialect: Optional[SqlDialect] = None,
) -> str:
    """Compile ``plan`` against ``catalog`` and return a single SQL string."""
    if isinstance(plan, dict):
        plan = Plan.from_dict(plan)
    if not isinstance(plan, Plan):
        raise TypeError("plan must be a Plan or a dict")

    D = dialect if dialect is not None else get_dialect()

    # ---- limit clamp (mirror PL/pgSQL) ----
    limit = plan.limit if plan.limit is not None else _DEFAULT_LIMIT
    if limit < _MIN_LIMIT:
        limit = _DEFAULT_LIMIT
    if limit > _MAX_LIMIT:
        limit = _MAX_LIMIT

    # ---- SELECT dims + metrics ----
    select_dims: List[str] = []
    group_by: List[str] = []
    for dkey in plan.dimensions:
        dim = catalog.dimension(dkey)
        if dim is None:
            raise UnknownDimensionError(f"Unknown dimension: {dkey}")
        expr = _emit_dimension_expression(dim.sql_expression, D, dkey)
        select_dims.append(f'{expr} AS {D.quote_ident(dkey)}')
        group_by.append(expr)

    select_mets: List[str] = []
    for mkey in plan.metrics:
        met = catalog.metric(mkey)
        if met is None:
            raise UnknownMetricError(f"Unknown metric: {mkey}")
        expr = _emit_metric_expression(met.sql_expression, met.agg, D)
        select_mets.append(f'{expr} AS {D.quote_ident(mkey)}')

    if not select_dims and not select_mets:
        raise EmptyPlanError("Plan must include metrics or dimensions")

    # ---- WHERE ----
    where_parts: List[str] = ["1=1"]
    for f in plan.filters:
        clause = _normalize_filter_clause(_emit_filter(f, catalog, D))
        if clause:
            where_parts.append(clause)

    # ---- ORDER BY (first sort entry that resolves) ----
    order_clause = ""
    for s in plan.sort:
        if catalog.has_metric(s.field) or catalog.has_dimension(s.field):
            order_clause = f' ORDER BY {D.quote_ident(s.field)} {s.dir.upper()}'
            break

    # ---- assemble ----
    select_list = ", ".join(select_dims + select_mets)
    sql = f"SELECT {select_list} FROM {catalog.base_view} {catalog.base_alias} WHERE {' AND '.join(where_parts)}"
    if group_by:
        sql += " GROUP BY " + ", ".join(group_by)
    sql += order_clause

    sql = D.apply_limit(sql, limit)
    return _ensure_single_trailing_semicolon(sql)


# ---- helpers --------------------------------------------------------------
def _emit_dimension_expression(raw_expr: str, dialect: SqlDialect, key: str) -> str:
    """Translate a stored dimension expression into a dialect-correct one.

    On PostgreSQL we keep the expression byte-identical (including casts)
    so the compiled SQL matches ``bi_meta.compile_query``. On SQL Server
    we strip ``::cast`` suffixes and refuse expressions that use
    ``date_trunc`` / ``extract`` (Phase C2 will add T-SQL equivalents).
    """
    if dialect.name == "postgres":
        return raw_expr
    if _PG_DATE_FUNCS.search(raw_expr):
        raise UnsupportedDimensionForBackend(
            f"Dimension {key!r} uses PostgreSQL-only date functions "
            f"({raw_expr!r}); add T-SQL equivalents in Phase C2."
        )
    return _strip_pg_casts(raw_expr).strip()


def _emit_metric_expression(raw_expr: str, agg: str, dialect: SqlDialect) -> str:
    """Translate a stored metric expression into a dialect-correct one.

    Postgres: keep verbatim.
    SQL Server:
      - Replace any ``count(*)::bigint`` with ``dialect.bigint_count()``.
      - For numeric aggregates, strip the ``::numeric`` cast(s) and
        re-wrap with ``dialect.cast_numeric``.
    """
    if dialect.name == "postgres":
        return raw_expr

    if (agg or "").lower() == "count" or _COUNT_STAR.fullmatch(raw_expr.strip()):
        return dialect.bigint_count()

    m = _NUMERIC_AGG_INNER.match(raw_expr.strip())
    if m:
        fn = m.group("fn").upper()
        inner = _strip_pg_casts(m.group("inner")).strip()
        return dialect.cast_numeric(f"{fn}({inner})")

    # Fallback: just strip casts. This keeps simple non-aggregate
    # expressions (e.g. raw column references) working.
    return _strip_pg_casts(raw_expr).strip()


def _emit_filter(f: Filter, catalog: Catalog, dialect: SqlDialect) -> str:
    op = (f.op or "").lower()
    if op not in _ALL_OPS:
        raise UnsupportedFilterOpError(f"Unsupported operator: {f.op!r}")

    dim = catalog.dimension(f.field)
    if dim is None:
        raise UnknownDimensionError(
            f"Unknown filter field (dimension): {f.field}"
        )
    dim_expr = _emit_dimension_expression(dim.sql_expression, dialect, f.field)

    if op in _COMPARISON_OPS:
        return f"{dim_expr} {op} {_quote_literal(f.value)}"

    if op == "ilike":
        # Dialect chooses ILIKE (PG) or LIKE (SQL Server CI collation).
        return dialect.ilike(dim_expr, _quote_literal(f.value))

    if op == "between":
        if not isinstance(f.value, (list, tuple)) or len(f.value) != 2:
            raise InvalidFilterValueError(
                f"BETWEEN expects a 2-element list for {f.field}"
            )
        lo, hi = f.value
        return f"{dim_expr} BETWEEN {_quote_literal(lo)} AND {_quote_literal(hi)}"

    # op == "in"
    if not isinstance(f.value, (list, tuple)):
        raise InvalidFilterValueError(
            f"IN expects an array value for {f.field}"
        )
    if not f.value:
        # Mirror PG behaviour: empty IN never matches.
        return "1=0"
    in_list = ", ".join(_quote_literal(v) for v in f.value)
    return f"{dim_expr} IN ({in_list})"


def _normalize_filter_clause(clause: str) -> str:
    """Return a bare predicate without leading boolean glue.

    Older compiler fragments included a leading ``AND``. Keeping this
    normalizer at the join boundary prevents accidental ``AND AND`` /
    ``WHERE AND`` if a future filter helper regresses or a custom fragment
    arrives already prefixed.
    """
    s = str(clause or "").strip()
    while True:
        cleaned = _LEADING_BOOLEAN.sub("", s, count=1).strip()
        if cleaned == s:
            return cleaned
        s = cleaned


def _ensure_single_trailing_semicolon(sql: str) -> str:
    return sql.rstrip().rstrip(";").rstrip() + ";"


__all__ = ["compile_plan"]
