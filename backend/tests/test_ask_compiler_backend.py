"""/ask + COMPILER_BACKEND dispatch (Phase C2).

Covers:
- Default backend value is "db" so PG behaviour is preserved.
- compile_for_request returns (sql, "db") on PG when COMPILER_BACKEND=db
  and (sql, "python") when COMPILER_BACKEND=python.
- The Python compiler path works end-to-end on both PG and SQL Server
  (catalog + executor are mocked so the test stays DB-free).
- The legacy db path on SQL Server still returns the Phase B 501 with
  a Phase C2 hint to set COMPILER_BACKEND=python.
- Cache and query_log writes are portable on SQL Server.
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend.app.core.config import settings
from backend.app.db import adapter
from backend.app.services.ask import compile as ask_compile
from backend.app.services.ask import runner as ask_runner


# Live catalog shape (trimmed) for compiler dispatch tests.
CATALOG = {
    "schema": "bi",
    "base_view": "bi.vw_fact_sales_line_clean",
    "metrics": [
        {"key": "net_sales", "agg": "sum", "sql": "sum(f.order_total::numeric)", "data_type": "numeric"},
        {"key": "order_count", "agg": "count", "sql": "COUNT(*)::bigint", "data_type": "integer"},
    ],
    "dimensions": [
        {"key": "city", "sql": "f.city", "data_type": "text"},
    ],
}

SQLSERVER_COMPLEX_CATALOG = {
    "schema": "bi",
    "base_view": "bi.vw_fact_sales_line_clean",
    "metrics": [
        {"key": "net_sales", "agg": "sum", "sql": "SUM(f.order_total)", "data_type": "numeric"},
        {"key": "gross_profit", "agg": "sum", "sql": "SUM(f.gross_profit)", "data_type": "numeric"},
        {"key": "discount_amount", "agg": "sum", "sql": "SUM(f.discount_amount)", "data_type": "numeric"},
        {"key": "order_count", "agg": "count", "sql": "COUNT(*)", "data_type": "integer"},
    ],
    "dimensions": [
        {"key": "city", "sql": "f.city", "data_type": "text"},
        {"key": "product_name", "sql": "f.product_name", "data_type": "text"},
        {"key": "order_year", "sql": "DATEPART(year, f.order_date_d)", "data_type": "integer"},
        {"key": "order_quarter", "sql": "DATEPART(quarter, f.order_date_d)", "data_type": "integer"},
    ],
}

COMPLEX_ARABIC_QUESTION = (
    "اعرض صافي المبيعات والربح الإجمالي وإجمالي الخصومات وعدد الطلبات حسب اسم المنتج "
    "والربع من مدينة سيدني خلال سنة 2015، ورتب النتائج حسب الربح الإجمالي تنازلياً "
    "واعرض أول 8 صفوف فقط"
)


# ============================================================================
# Default behaviour
# ============================================================================
def test_default_compiler_backend_is_db():
    # Settings default; no env override required.
    assert ask_compile.active_compiler_backend() == "db"


def test_unknown_compiler_backend_falls_back_to_db(monkeypatch):
    monkeypatch.setattr(settings, "compiler_backend", "wat", raising=False)
    assert ask_compile.active_compiler_backend() == "db"


# ============================================================================
# Compiler dispatch (no DB connection needed for the python path)
# ============================================================================
class TestCompileDispatch:
    PLAN = {
        "metrics": ["net_sales"],
        "dimensions": ["city"],
        "sort": [{"field": "net_sales", "dir": "desc"}],
        "limit": 5,
    }

    def test_python_path_does_not_touch_db(self, monkeypatch):
        monkeypatch.setattr(settings, "compiler_backend", "python", raising=False)
        # Sentinel: if anything tried to touch asyncpg, this would raise.
        monkeypatch.setattr(
            ask_compile, "pg_fetchval",
            lambda *a, **k: (_ for _ in ()).throw(AssertionError("DB used in python path")),
        )
        sql, used = asyncio.run(ask_compile.compile_for_request(self.PLAN, CATALOG))
        assert used == "python"
        assert "f.city AS" in sql
        assert "sum(f.order_total::numeric) AS" in sql  # PG dialect (default)
        assert sql.rstrip(";").rstrip().endswith("LIMIT 5")
        assert sql.endswith(";")

    def test_python_path_uses_sqlserver_dialect_when_active(self, monkeypatch):
        monkeypatch.setattr(settings, "compiler_backend", "python", raising=False)
        monkeypatch.setattr(settings, "database_backend", "sqlserver", raising=False)
        sql, used = asyncio.run(ask_compile.compile_for_request(self.PLAN, CATALOG))
        assert used == "python"
        upper = sql.upper()
        assert "TOP (5)" in sql
        assert "::NUMERIC" not in upper
        assert "::BIGINT" not in upper
        assert "ILIKE" not in upper

    def test_db_path_rejects_sqlserver(self, monkeypatch):
        monkeypatch.setattr(settings, "compiler_backend", "db", raising=False)
        monkeypatch.setattr(settings, "database_backend", "sqlserver", raising=False)
        with pytest.raises(adapter.BackendNotSupportedError) as ei:
            asyncio.run(ask_compile.compile_for_request(self.PLAN, CATALOG))
        assert "COMPILER_BACKEND=python" in str(ei.value)


# ============================================================================
# /ask end-to-end with the python compiler (catalog + executor mocked)
# ============================================================================
class _Captured:
    """Holder used by the executor mock so tests can inspect the SQL."""
    def __init__(self):
        self.last_sql: str | None = None


def _install_runner_mocks(monkeypatch, captured: _Captured, *, pg_logging_should_be_called=True):
    """Patch the catalog loader and executor so /ask runs without a DB.

    Returns ``capture_state`` populated by the executor when called.
    """
    async def fake_catalog(schema="bi"):
        return CATALOG, "mock"

    async def fake_fetch_select(sql: str):
        captured.last_sql = sql
        # Return a single fake row matching the SELECT alias contract.
        return [{"city": "Sydney", "net_sales": 100.0}]

    # Disable pg_logging side-channels so the test never opens asyncpg.
    async def fake_db_fetchval(*a, **k):
        # Tests should not depend on this being called; only the
        # PG-only query_log insert reaches here when running under
        # database_backend=postgres.
        if not pg_logging_should_be_called:
            raise AssertionError("Unexpected asyncpg call in test")
        return None  # log_id = None

    async def fake_db_fetchrow(*a, **k):
        return None  # cache miss

    async def fake_get_cached_plan(*a, **k):
        return None

    async def fake_touch_cached_plan(*a, **k):
        return None

    async def fake_upsert_cached_plan(*a, **k):
        return None

    async def fake_insert_query_log(*a, **k):
        return None

    monkeypatch.setattr(ask_runner, "_get_catalog_with_source", fake_catalog)
    monkeypatch.setattr(ask_runner, "fetch_select", fake_fetch_select)
    monkeypatch.setattr(ask_runner, "_db_fetchval", fake_db_fetchval)
    monkeypatch.setattr(ask_runner, "_db_fetchrow", fake_db_fetchrow)
    monkeypatch.setattr(ask_runner, "get_cached_plan", fake_get_cached_plan)
    monkeypatch.setattr(ask_runner, "touch_cached_plan", fake_touch_cached_plan)
    monkeypatch.setattr(ask_runner, "upsert_cached_plan", fake_upsert_cached_plan)
    monkeypatch.setattr(ask_runner, "insert_query_log", fake_insert_query_log)


def test_ask_uses_python_compiler_on_postgres(monkeypatch):
    monkeypatch.setattr(settings, "compiler_backend", "python", raising=False)
    monkeypatch.setattr(settings, "database_backend", "postgres", raising=False)

    cap = _Captured()
    _install_runner_mocks(monkeypatch, cap)

    body = SimpleNamespace(question="صافي المبيعات حسب المدينة")
    out = asyncio.run(ask_runner.ask(body))

    assert out["meta"]["compiler_backend"] == "python"
    assert out["meta"]["skipped_for_sqlserver"] is None
    # SQL was generated by the Python compiler against the mocked catalog.
    assert cap.last_sql is not None
    assert "FROM bi.vw_fact_sales_line_clean f" in cap.last_sql
    assert cap.last_sql.endswith(";")
    # Result shape preserved.
    assert out["question"] == "صافي المبيعات حسب المدينة"
    assert isinstance(out["plan"], dict)
    assert "sql" in out["result"]
    assert isinstance(out["result"]["rows"], list)


def test_ask_uses_python_compiler_on_sqlserver_and_uses_portable_sidechannels(monkeypatch):
    monkeypatch.setattr(settings, "compiler_backend", "python", raising=False)
    monkeypatch.setattr(settings, "database_backend", "sqlserver", raising=False)

    cap = _Captured()
    _install_runner_mocks(monkeypatch, cap, pg_logging_should_be_called=False)

    body = SimpleNamespace(question="صافي المبيعات حسب المدينة")
    out = asyncio.run(ask_runner.ask(body))

    # No more Phase B 501 when compiler_backend=python.
    assert out["meta"]["compiler_backend"] == "python"

    # Cache/log side channels are now portable; compatibility field remains.
    assert out["meta"]["skipped_for_sqlserver"] is None
    assert out["meta"]["log_id"] is None

    # Generated SQL uses the SQL Server dialect.
    upper = (cap.last_sql or "").upper()
    assert "TOP (" in upper
    import re
    assert not re.search(r"\bLIMIT\s+\d+", upper)
    assert "::BIGINT" not in upper
    assert "::NUMERIC" not in upper


def test_ask_uses_sqlserver_catalog_loader(monkeypatch):
    """Phase C3: on SQL Server the runner must call the new
    load_sqlserver_catalog helper instead of bi_meta.get_catalog()."""
    from backend.app.services import catalog_loader

    monkeypatch.setattr(settings, "compiler_backend", "python", raising=False)
    monkeypatch.setattr(settings, "database_backend", "sqlserver", raising=False)

    called = {"sqlserver_catalog": False, "pg_fetchval": False}

    async def fake_sql_loader(schema: str):
        called["sqlserver_catalog"] = True
        return {
            "schema": "bi",
            "base_view": "bi.vw_fact_sales_line_clean",
            "metrics": [
                {"key": "net_sales", "agg": "sum", "sql": "sum(f.order_total)"},
            ],
            "dimensions": [
                {"key": "city", "sql": "f.city"},
                {"key": "order_year", "sql": "DATEPART(year, f.order_date_d)"},
            ],
            "synonyms": [],
        }

    async def fake_fetch_select(sql: str):
        return [{"city": "Sydney", "net_sales": 1.0}]

    async def fake_get_cached_plan(*a, **k):
        return None

    async def fake_upsert_cached_plan(*a, **k):
        return None

    async def fake_insert_query_log(*a, **k):
        return None

    async def boom(*a, **k):  # asyncpg helpers must not run on SQL Server
        called["pg_fetchval"] = True
        raise AssertionError("asyncpg used in sqlserver path")

    monkeypatch.setattr(catalog_loader, "load_sqlserver_catalog", fake_sql_loader)
    monkeypatch.setattr(ask_runner, "fetch_select", fake_fetch_select)
    monkeypatch.setattr(ask_runner, "get_cached_plan", fake_get_cached_plan)
    monkeypatch.setattr(ask_runner, "upsert_cached_plan", fake_upsert_cached_plan)
    monkeypatch.setattr(ask_runner, "insert_query_log", fake_insert_query_log)
    monkeypatch.setattr(ask_runner, "_db_fetchval", boom)
    monkeypatch.setattr(ask_runner, "_db_fetchrow", boom)

    body = SimpleNamespace(question="صافي المبيعات حسب المدينة")
    out = asyncio.run(ask_runner.ask(body))

    assert called["sqlserver_catalog"] is True
    assert called["pg_fetchval"] is False
    assert out["meta"]["compiler_backend"] == "python"
    assert out["meta"]["catalog_source"] == "sqlserver_tables"


def test_ask_sqlserver_complex_filters_do_not_duplicate_boolean_glue(monkeypatch):
    monkeypatch.setattr(settings, "compiler_backend", "python", raising=False)
    monkeypatch.setattr(settings, "database_backend", "sqlserver", raising=False)

    expected_plan = {
        "metrics": ["net_sales", "gross_profit", "discount_amount", "order_count"],
        "dimensions": ["product_name", "order_quarter", "order_year"],
        "filters": [
            {"field": "city", "op": "in", "value": ["Sydney"]},
            {"field": "order_year", "op": "in", "value": [2015]},
        ],
        "sort": [{"field": "gross_profit", "dir": "desc"}],
        "limit": 8,
        "notes": "regression",
    }

    async def fake_catalog(schema="bi"):
        return SQLSERVER_COMPLEX_CATALOG, "mock"

    async def fake_fetch_select(sql: str):
        cap.last_sql = sql
        return [{"product_name": "Example", "order_quarter": 1, "order_year": 2015}]

    async def fake_insert_query_log(*a, **k):
        return 42

    cap = _Captured()
    monkeypatch.setattr(ask_runner, "_get_catalog_with_source", fake_catalog)
    monkeypatch.setattr(ask_runner, "fetch_select", fake_fetch_select)
    monkeypatch.setattr(ask_runner, "_rule_based_plan", lambda question, catalog: dict(expected_plan))
    monkeypatch.setattr(ask_runner, "insert_query_log", fake_insert_query_log)

    out = asyncio.run(
        ask_runner.ask(
            SimpleNamespace(question=COMPLEX_ARABIC_QUESTION),
            use_llm=False,
            use_cache=False,
        )
    )

    sql = cap.last_sql or ""
    upper = " ".join(sql.upper().split())
    assert out["meta"]["compiler_backend"] == "python"
    assert out["meta"]["skipped_for_sqlserver"] is None
    assert out["meta"]["log_id"] == 42
    assert "AND AND" not in upper
    assert "WHERE AND" not in upper
    assert "OR OR" not in upper
    assert "WHERE OR" not in upper
    assert "TOP (8)" in sql
    assert "f.city IN ('Sydney')" in sql
    assert "DATEPART(year, f.order_date_d) IN (2015)" in sql
    assert "LIMIT" not in upper
    assert "::BIGINT" not in upper
    assert "::NUMERIC" not in upper
    assert "ILIKE" not in upper
    assert "JSONB" not in upper


def test_ask_db_path_still_501_on_sqlserver_with_phase_c2_hint(monkeypatch):
    monkeypatch.setattr(settings, "compiler_backend", "db", raising=False)
    monkeypatch.setattr(settings, "database_backend", "sqlserver", raising=False)

    body = SimpleNamespace(question="صافي المبيعات")
    with pytest.raises(HTTPException) as ei:
        asyncio.run(ask_runner.ask(body))

    assert ei.value.status_code == 501
    assert "COMPILER_BACKEND=python" in ei.value.detail
    assert "bi_meta" in ei.value.detail
