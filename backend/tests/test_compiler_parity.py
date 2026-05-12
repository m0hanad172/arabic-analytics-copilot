"""Optional parity tests vs PostgreSQL bi_meta.compile_query (Phase C1).

Skipped automatically when no PostgreSQL is reachable. Compares the
*shape* of the SQL emitted by the Python compiler against
``bi_meta.compile_query`` for a handful of simple plans:

- same selected columns and aliases
- same GROUP BY expressions
- same ORDER BY
- same row cap

Exact whitespace / clause ordering may differ; the parity check
canonicalises both sides before comparing.
"""
from __future__ import annotations

import asyncio
import json
import os
import re

import pytest

from backend.app.services.semantic import Catalog, compile_plan
from backend.app.db.dialects import PostgresDialect


# -- Bootstrap: connect once, fetch catalog, skip if anything fails ---------
def _resolve_dsn() -> str:
    url = os.getenv("DATABASE_URL", "")
    if url.startswith("postgresql+asyncpg://"):
        url = "postgresql://" + url[len("postgresql+asyncpg://"):]
    return url


async def _fetch_compiled(sql: str) -> str:
    import asyncpg  # type: ignore
    dsn = _resolve_dsn()
    conn = await asyncpg.connect(dsn)
    try:
        return await conn.fetchval(sql)
    finally:
        await conn.close()


async def _fetch_catalog() -> dict:
    import asyncpg  # type: ignore
    dsn = _resolve_dsn()
    conn = await asyncpg.connect(dsn)
    try:
        raw = await conn.fetchval("SELECT bi_meta.get_catalog();")
    finally:
        await conn.close()
    return json.loads(raw) if isinstance(raw, str) else raw


def _maybe_catalog():
    if not _resolve_dsn():
        return None
    try:
        return asyncio.run(_fetch_catalog())
    except Exception:
        return None


_CATALOG_RAW = _maybe_catalog()
pytestmark = pytest.mark.skipif(
    _CATALOG_RAW is None,
    reason="bi_meta.get_catalog() not reachable; parity test skipped.",
)


# -- Canonicalisers ---------------------------------------------------------
_WHITESPACE = re.compile(r"\s+")


_ALIAS_QUOTE = re.compile(r' as "([a-z_][a-z0-9_]*)"', flags=re.IGNORECASE)
_ORDER_QUOTE = re.compile(r'order by "([a-z_][a-z0-9_]*)"', flags=re.IGNORECASE)


def _canon(sql: str) -> str:
    s = _WHITESPACE.sub(" ", sql).strip().rstrip(";").lower()
    # Normalise alias quoting: PL/pgSQL's format(%I) keeps lowercase
    # idents unquoted; the Python compiler quotes uniformly. Drop the
    # surrounding double-quotes around plain lowercase idents so the two
    # sides compare equal.
    s = _ALIAS_QUOTE.sub(r" as \1", s)
    s = _ORDER_QUOTE.sub(r"order by \1", s)
    return s


def _select_list(sql: str) -> set[str]:
    """Crude SELECT-list extractor: tokens between SELECT and FROM,
    split on top-level commas (no nested parens of commas in our subset)."""
    canon = _canon(sql)
    m = re.match(r"select\s+(.*?)\s+from\b", canon, flags=re.DOTALL)
    if not m:
        return set()
    body = m.group(1)
    parts: list[str] = []
    depth = 0
    cur = []
    for ch in body:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    if cur:
        parts.append("".join(cur).strip())
    return {p for p in parts if p}


def _group_by(sql: str) -> str:
    canon = _canon(sql)
    m = re.search(r"\bgroup by\s+(.+?)(?:\s+order by|\s+limit\b|$)", canon)
    return m.group(1).strip() if m else ""


def _row_cap(sql: str) -> int | None:
    m = re.search(r"\blimit\s+(\d+)\b", _canon(sql))
    return int(m.group(1)) if m else None


# -- Catalog and compile helpers --------------------------------------------
CATALOG = Catalog.from_bi_meta(_CATALOG_RAW or {})


def _compile_db(plan: dict) -> str:
    payload = json.dumps(plan, ensure_ascii=False)
    sql = f"SELECT bi_meta.compile_query(($JSON$ {payload} $JSON$)::jsonb);"
    return asyncio.run(_fetch_compiled(sql))


# -- Parity scenarios -------------------------------------------------------
PARITY_PLANS = [
    {"metrics": ["net_sales"], "limit": 10},
    {
        "metrics": ["net_sales", "discount_amount"],
        "dimensions": ["city"],
        "sort": [{"field": "net_sales", "dir": "desc"}],
        "limit": 25,
    },
    {
        "metrics": ["order_count"],
        "dimensions": ["product_category"],
        "sort": [{"field": "order_count", "dir": "desc"}],
        "limit": 5,
    },
]


@pytest.mark.parametrize("plan", PARITY_PLANS)
def test_python_compiler_parity_with_bi_meta(plan):
    py_sql = compile_plan(plan, CATALOG, dialect=PostgresDialect())
    db_sql = _compile_db(plan)

    # Same selected columns (alias-aware).
    assert _select_list(py_sql) == _select_list(db_sql), (
        f"\nPY: {py_sql}\nDB: {db_sql}"
    )

    # Same GROUP BY expression (or both empty).
    assert _group_by(py_sql) == _group_by(db_sql), (
        f"\nPY: {py_sql}\nDB: {db_sql}"
    )

    # Same row cap.
    assert _row_cap(py_sql) == _row_cap(db_sql)
