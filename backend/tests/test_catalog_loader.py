"""Portable catalog loader tests (Phase C3).

The loader's pure assembly function ``_build_catalog_dict`` is exercised
with synthetic rows so the test never opens a SQLAlchemy connection.
"""
from __future__ import annotations

import asyncio

import pytest

from backend.app.services import catalog_loader
from backend.app.services.semantic import Catalog, compile_plan
from backend.app.db.dialects import SqlServerDialect, PostgresDialect


# Mocked row shapes that mirror what the SQL Server tables return.
METRIC_ROWS = [
    {
        "metric_key": "net_sales", "display_name_ar": "صافي المبيعات",
        "display_name_en": "Net Sales", "agg": "sum",
        "sql_expression": "sum(f.order_total)", "data_type": "numeric",
        "format_hint": "money",
    },
    {
        "metric_key": "order_count", "display_name_ar": "عدد السطور",
        "display_name_en": "Row Count", "agg": "count",
        "sql_expression": "COUNT_BIG(*)", "data_type": "integer",
        "format_hint": None,
    },
]

DIMENSION_ROWS = [
    {
        "dim_key": "city", "display_name_ar": "المدينة", "display_name_en": "City",
        "sql_expression": "f.city", "data_type": "text", "allowed_grouping": 1,
    },
    {
        "dim_key": "order_year", "display_name_ar": "السنة", "display_name_en": "Year",
        "sql_expression": "DATEPART(year, f.order_date_d)",
        "data_type": "integer", "allowed_grouping": 1,
    },
    {
        "dim_key": "month_start", "display_name_ar": "بداية الشهر",
        "display_name_en": "Month Start",
        "sql_expression": "DATEFROMPARTS(YEAR(f.order_date_d), MONTH(f.order_date_d), 1)",
        "data_type": "date", "allowed_grouping": 1,
    },
]

SYNONYM_ROWS = [
    {"term": "city", "maps_to_type": "dimension", "maps_to_key": "city"},
    {"term": "net sales", "maps_to_type": "metric", "maps_to_key": "net_sales"},
]


# ---- pure assembly --------------------------------------------------------
def test_build_catalog_dict_matches_get_catalog_shape():
    cat = catalog_loader._build_catalog_dict(
        schema="bi",
        metrics_rows=METRIC_ROWS,
        dimensions_rows=DIMENSION_ROWS,
        synonyms_rows=SYNONYM_ROWS,
    )
    assert cat["schema"] == "bi"
    assert cat["base_view"] == "bi.vw_fact_sales_line_clean"
    # metric fields use the same keys as bi_meta.get_catalog()
    m0 = cat["metrics"][0]
    assert m0["key"] == "net_sales"
    assert m0["agg"] == "sum"
    assert m0["sql"] == "sum(f.order_total)"
    assert m0["data_type"] == "numeric"
    # dimensions
    d0 = cat["dimensions"][0]
    assert d0["key"] == "city"
    assert d0["sql"] == "f.city"
    assert d0["allowed_grouping"] is True
    # synonyms
    s0 = cat["synonyms"][0]
    assert s0 == {"term": "city", "type": "dimension", "key": "city"}


def test_built_catalog_is_consumable_by_compiler():
    raw = catalog_loader._build_catalog_dict(
        schema="bi",
        metrics_rows=METRIC_ROWS,
        dimensions_rows=DIMENSION_ROWS,
        synonyms_rows=SYNONYM_ROWS,
    )
    cat = Catalog.from_bi_meta(raw)
    assert cat.has_metric("net_sales")
    assert cat.has_dimension("city")
    assert cat.has_dimension("order_year")

    sql = compile_plan(
        {"metrics": ["net_sales"], "dimensions": ["city"], "limit": 5},
        cat, dialect=SqlServerDialect(),
    )
    upper = sql.upper()
    assert "TOP (5)" in sql
    assert "f.city AS [city]" in sql
    # The catalog stored a non-PG metric expression with no ::numeric; the
    # compiler should still wrap it as CAST(... AS NUMERIC(...)).
    assert "CAST(SUM(f.order_total) AS NUMERIC" in sql


# ---- dispatch -------------------------------------------------------------
def test_load_catalog_for_active_backend_uses_sqlserver_loader(monkeypatch):
    from backend.app.core.config import settings

    monkeypatch.setattr(settings, "database_backend", "sqlserver", raising=False)

    async def fake_sql_loader(schema: str):
        assert schema == "bi"
        return catalog_loader._build_catalog_dict(
            schema=schema,
            metrics_rows=METRIC_ROWS,
            dimensions_rows=DIMENSION_ROWS,
            synonyms_rows=SYNONYM_ROWS,
        )

    monkeypatch.setattr(catalog_loader, "load_sqlserver_catalog", fake_sql_loader)
    cat = asyncio.run(catalog_loader.load_catalog_for_active_backend("bi"))
    assert cat["schema"] == "bi"
    assert any(m["key"] == "net_sales" for m in cat["metrics"])


def test_load_catalog_for_active_backend_uses_pg_path(monkeypatch):
    """On PG the loader should delegate to runner._db_fetchval."""
    from backend.app.core.config import settings
    from backend.app.services.ask import runner as ask_runner

    monkeypatch.setattr(settings, "database_backend", "postgres", raising=False)

    captured = {"called": False}

    async def fake_db_fetchval(sql, *args):
        captured["called"] = True
        # Simulate bi_meta.get_catalog() output minimally.
        return {"schema": "bi", "metrics": [], "dimensions": [], "synonyms": []}

    monkeypatch.setattr(ask_runner, "_db_fetchval", fake_db_fetchval)
    cat = asyncio.run(catalog_loader.load_catalog_for_active_backend("bi"))
    assert captured["called"]
    assert cat["schema"] == "bi"
