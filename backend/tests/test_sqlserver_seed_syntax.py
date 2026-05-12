"""Static checks on the SQL Server schema/seed scripts (Phase C3).

These tests do *not* touch a real database. They guard the .sql files
against accidental PostgreSQL syntax sneaking back in during edits.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest


SQL_DIR = Path(__file__).resolve().parents[2] / "backend" / "db" / "sqlserver"
SQL_FILES = [
    "001_create_database.sql",
    "002_create_schemas.sql",
    "003_create_bi_objects.sql",
    "004_create_bi_meta_objects.sql",
    "005_seed_bi_meta.sql",
]


# PG-only tokens that must never appear in a T-SQL script.
PG_FORBIDDEN = [
    "::numeric",
    "::bigint",
    "::int",
    "::date",
    "jsonb",
    "ON CONFLICT",
    "ILIKE",
    "date_trunc",
    re.compile(r"\bextract\s*\(", re.IGNORECASE),
    re.compile(r"\bLIMIT\s+\d", re.IGNORECASE),
    re.compile(r"\bnow\s*\(\s*\)", re.IGNORECASE),
]


@pytest.mark.parametrize("name", SQL_FILES)
def test_sql_file_has_no_postgres_tokens(name):
    text = (SQL_DIR / name).read_text(encoding="utf-8")
    for tok in PG_FORBIDDEN:
        if isinstance(tok, str):
            assert tok.lower() not in text.lower(), f"PG token {tok!r} found in {name}"
        else:
            assert not tok.search(text), f"PG pattern {tok.pattern!r} found in {name}"


def test_seed_contains_all_13_metrics():
    text = (SQL_DIR / "005_seed_bi_meta.sql").read_text(encoding="utf-8")
    for key in [
        "avg_discount_pct", "avg_ship_delay_days", "cogs", "discount_amount",
        "discounts", "gross_profit", "gross_sales", "line_count",
        "net_sales", "order_count", "profit_after_shipping",
        "shipping_cost", "units",
    ]:
        assert f"N'{key}'" in text, f"metric {key} missing from seed"


def test_seed_contains_all_13_dimensions():
    text = (SQL_DIR / "005_seed_bi_meta.sql").read_text(encoding="utf-8")
    for key in [
        "account_manager", "city", "customer_type", "month_start",
        "order_date", "order_month", "order_priority", "order_quarter",
        "order_year", "product_category", "product_name", "ship_mode",
        "state",
    ]:
        assert f"N'{key}'" in text, f"dimension {key} missing from seed"


def test_seed_uses_tsql_date_expressions():
    text = (SQL_DIR / "005_seed_bi_meta.sql").read_text(encoding="utf-8")
    assert "DATEPART(year, f.order_date_d)" in text
    assert "DATEPART(quarter, f.order_date_d)" in text
    assert "DATEPART(month, f.order_date_d)" in text
    assert "DATEFROMPARTS(YEAR(f.order_date_d), MONTH(f.order_date_d), 1)" in text


def test_seed_uses_count_big_for_counts():
    text = (SQL_DIR / "005_seed_bi_meta.sql").read_text(encoding="utf-8")
    assert "COUNT_BIG(*)" in text
    # And no PG count cast slipped through.
    assert "count(*)::bigint" not in text.lower()


def test_seed_synonyms_block_has_at_least_50_entries():
    # Live PG ships 54; the merge VALUES list must reflect them.
    text = (SQL_DIR / "005_seed_bi_meta.sql").read_text(encoding="utf-8")
    syn_start = text.lower().find("bi_meta.synonyms")
    assert syn_start != -1
    body = text[syn_start:]
    # Each VALUES row begins with "    (N'..."; count those.
    rows = re.findall(r"^    \(N'", body, flags=re.MULTILINE)
    assert len(rows) >= 50, f"synonyms count too low: {len(rows)}"


def test_003_creates_view_aliasing_date_columns():
    text = (SQL_DIR / "003_create_bi_objects.sql").read_text(encoding="utf-8")
    assert "AS order_date_d" in text
    assert "AS ship_date_d" in text
    assert "bi.vw_fact_sales_line_clean" in text


def test_004_creates_unique_index_on_plan_cache():
    text = (SQL_DIR / "004_create_bi_meta_objects.sql").read_text(encoding="utf-8")
    assert "UX_bi_meta_plan_cache_question_catalog" in text
    assert "(question_norm, catalog_hash)" in text
