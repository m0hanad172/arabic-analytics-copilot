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


# ---- Nullability guard ----------------------------------------------------
# Every business column in bi.fact_sales_line must be nullable. The CSV
# import (SSMS Import Flat File / bcp) fails with "Column '<x>' does not
# allow DBNull.Value" when a destination column is NOT NULL but the CSV
# has blank cells in it. We assert:
#   (a) the CREATE TABLE declares it NULL, AND
#   (b) the script issues an idempotent ALTER COLUMN ... NULL to heal a
#       table that was created from an older draft with NOT NULL.
_FACT_SALES_LINE_COLUMNS = [
    "order_no", "order_date", "ship_date", "ship_delay_days",
    "customer_type", "account_manager", "order_priority",
    "product_name", "product_category", "product_container", "ship_mode",
    "city", "state",
    "cost_price", "retail_price", "order_quantity",
    "sub_total", "discount_pct", "discount_amount", "order_total",
    "shipping_cost", "total", "cogs", "gross_profit",
    "profit_after_shipping",
    "order_year", "order_month", "order_quarter",
]


@pytest.mark.parametrize("col", _FACT_SALES_LINE_COLUMNS)
def test_fact_sales_line_column_declared_nullable_in_create(col):
    text = (SQL_DIR / "003_create_bi_objects.sql").read_text(encoding="utf-8")
    # Find the CREATE TABLE bi.fact_sales_line block (up to the closing ");").
    create_start = text.find("CREATE TABLE bi.fact_sales_line")
    assert create_start != -1
    create_end = text.find("    );", create_start)
    assert create_end != -1
    create_body = text[create_start:create_end]

    # The column line must end with " NULL" (with optional trailing
    # comma — the last column in CREATE TABLE has no comma).
    pattern = re.compile(
        rf"^\s+{re.escape(col)}\s+\S.*?\sNULL,?\s*$",
        flags=re.MULTILINE,
    )
    not_null = re.compile(
        rf"^\s+{re.escape(col)}\s+\S.*?\sNOT\s+NULL",
        flags=re.MULTILINE | re.IGNORECASE,
    )
    assert pattern.search(create_body), f"Column {col} not declared NULL in CREATE TABLE"
    assert not not_null.search(create_body), f"Column {col} is NOT NULL in CREATE TABLE"


@pytest.mark.parametrize("col", _FACT_SALES_LINE_COLUMNS)
def test_fact_sales_line_has_alter_column_null_safety_net(col):
    """Re-running 003 must heal a table that was created earlier with
    NOT NULL constraints. We require an explicit ALTER COLUMN ... NULL
    for every business column."""
    text = (SQL_DIR / "003_create_bi_objects.sql").read_text(encoding="utf-8")
    alter = re.compile(
        rf"ALTER TABLE bi\.fact_sales_line\s+ALTER COLUMN\s+{re.escape(col)}\b.*\bNULL\s*;",
        flags=re.IGNORECASE,
    )
    assert alter.search(text), f"Missing ALTER COLUMN ... NULL safety net for {col}"


def test_gross_profit_is_nullable():
    """Pinned regression for the specific SSMS Import Flat File error
    'Column gross_profit does not allow DBNull.Value'."""
    text = (SQL_DIR / "003_create_bi_objects.sql").read_text(encoding="utf-8")
    # Bare CREATE TABLE line must be NULL.
    assert re.search(
        r"^\s+gross_profit\s+DECIMAL\(38,\s*6\)\s+NULL,\s*$",
        text, flags=re.MULTILINE,
    )
    # And the ALTER safety net must be present.
    assert re.search(
        r"ALTER TABLE bi\.fact_sales_line\s+ALTER COLUMN\s+gross_profit\b.*\bNULL\s*;",
        text, flags=re.IGNORECASE,
    )


def test_004_creates_unique_index_on_plan_cache():
    text = (SQL_DIR / "004_create_bi_meta_objects.sql").read_text(encoding="utf-8")
    assert "UX_bi_meta_plan_cache_question_catalog" in text
    assert "(question_norm, catalog_hash)" in text


# ---- Reserved-keyword guard ------------------------------------------------
# T-SQL reserved words that the project actively uses as column names.
# Each must appear bracketed ([plan], [sql], ...) in CREATE TABLE column
# lists; SSMS rejects the unbracketed form with
# "Incorrect syntax near the keyword '<word>'".
_TSQL_RESERVED_AS_COLNAMES = ["plan", "sql"]


@pytest.mark.parametrize("kw", _TSQL_RESERVED_AS_COLNAMES)
def test_reserved_keyword_columns_are_bracketed_in_create_table(kw):
    """Catch the SSMS error
    'Incorrect syntax near the keyword <kw>' by failing in CI if a
    column declaration ever uses the bare reserved name."""
    text = (SQL_DIR / "004_create_bi_meta_objects.sql").read_text(encoding="utf-8")

    # Forbid lines like "        plan            NVARCHAR(MAX)  NOT NULL,"
    # i.e. the bare keyword followed by whitespace and a type, at the
    # start of a column definition (anywhere not preceded by '[').
    bare_col = re.compile(
        rf"(?m)^(?!\s*--)\s+(?<!\[){re.escape(kw)}\s+(?:N?VARCHAR|INT|BIGINT|BIT|DATETIME|DECIMAL|DATE|FLOAT|MONEY)",
        flags=re.IGNORECASE,
    )
    assert not bare_col.search(text), (
        f"Unbracketed reserved keyword {kw!r} found as a column name in 004."
    )

    # And the bracketed form must exist (we *do* expect the column).
    bracketed = f"[{kw}]"
    assert bracketed in text, f"Expected bracketed {bracketed} in 004."


def test_query_log_has_bracketed_plan_and_sql_columns():
    text = (SQL_DIR / "004_create_bi_meta_objects.sql").read_text(encoding="utf-8")
    # Both columns must live inside the query_log create block.
    log_start = text.find("CREATE TABLE bi_meta.query_log")
    assert log_start != -1
    log_body = text[log_start:text.find("END", log_start)]
    assert "[plan]" in log_body
    assert "[sql]" in log_body


def test_plan_cache_has_bracketed_plan_column():
    text = (SQL_DIR / "004_create_bi_meta_objects.sql").read_text(encoding="utf-8")
    pc_start = text.find("CREATE TABLE bi_meta.plan_cache")
    assert pc_start != -1
    pc_body = text[pc_start:text.find("END", pc_start)]
    assert "[plan]" in pc_body
