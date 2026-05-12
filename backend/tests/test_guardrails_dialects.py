"""Guardrail tests across PG and SQL Server dialects (Phase A)."""
import pytest

from backend.app.core.sql_guardrails import guard_sql_or_raise
from backend.app.db.dialects import PostgresDialect, SqlServerDialect


# ----------------------------- Allowed shapes -----------------------------

def test_pg_select_passes_and_keeps_limit():
    sql = "SELECT * FROM bi.fact_sales_line LIMIT 10"
    out = guard_sql_or_raise(sql, max_rows=10, allowed_schemas={"bi"},
                             dialect=PostgresDialect())
    assert "LIMIT 10" in out


def test_pg_appends_limit_when_missing():
    sql = "SELECT * FROM bi.fact_sales_line"
    out = guard_sql_or_raise(sql, max_rows=25, allowed_schemas={"bi"},
                             dialect=PostgresDialect())
    assert "LIMIT 25" in out
    assert out.endswith(";")
    assert out.count(";") == 1


def test_sqlserver_top_select_passes_unmodified_row_cap():
    sql = "SELECT TOP (5) * FROM bi.fact_sales_line"
    out = guard_sql_or_raise(sql, max_rows=200, allowed_schemas={"bi"},
                             dialect=SqlServerDialect())
    # Already row-capped via TOP -> guardrails should not add LIMIT.
    assert "LIMIT" not in out.upper()
    assert "TOP (5)" in out


def test_sqlserver_injects_top_when_missing():
    sql = "SELECT * FROM bi.fact_sales_line"
    out = guard_sql_or_raise(sql, max_rows=42, allowed_schemas={"bi"},
                             dialect=SqlServerDialect())
    assert "TOP (42)" in out
    assert "LIMIT" not in out.upper()
    assert out.count(";") == 1


def test_with_cte_allowed():
    sql = "WITH x AS (SELECT 1 AS a) SELECT * FROM x"
    out = guard_sql_or_raise(sql, max_rows=5, allowed_schemas={"bi"},
                             dialect=PostgresDialect())
    assert out


# ----------------------------- Dangerous shapes still blocked -----------------------------

@pytest.mark.parametrize("bad", [
    "DROP TABLE bi.fact_sales_line",
    "DELETE FROM bi.fact_sales_line",
    "UPDATE bi.fact_sales_line SET city='x'",
    "INSERT INTO bi.fact_sales_line VALUES (1)",
    "ALTER TABLE bi.fact_sales_line ADD COLUMN c INT",
    "CREATE TABLE bi.x (id INT)",
    "TRUNCATE TABLE bi.fact_sales_line",
    "MERGE INTO bi.t USING bi.s ON 1=1 WHEN MATCHED THEN DELETE",
    "EXEC sp_who",
    "EXECUTE sp_who",
])
def test_dangerous_keywords_blocked_pg(bad):
    with pytest.raises(ValueError):
        guard_sql_or_raise(bad, max_rows=10, allowed_schemas={"bi"},
                           dialect=PostgresDialect())


@pytest.mark.parametrize("bad", [
    "DROP TABLE bi.fact_sales_line",
    "EXEC xp_cmdshell 'dir'",
    "SELECT * FROM bi.t; DROP TABLE bi.t",
])
def test_dangerous_blocked_sqlserver(bad):
    with pytest.raises(ValueError):
        guard_sql_or_raise(bad, max_rows=10, allowed_schemas={"bi"},
                           dialect=SqlServerDialect())


def test_multi_statement_blocked():
    with pytest.raises(ValueError):
        guard_sql_or_raise(
            "SELECT 1; SELECT 2;", max_rows=10, allowed_schemas={"bi"},
            dialect=PostgresDialect(),
        )


def test_comment_blocked():
    with pytest.raises(ValueError):
        guard_sql_or_raise(
            "SELECT * FROM bi.t -- bad",
            max_rows=10, allowed_schemas={"bi"},
            dialect=PostgresDialect(),
        )


def test_disallowed_schema_blocked_pg():
    with pytest.raises(ValueError):
        guard_sql_or_raise(
            "SELECT * FROM pg_catalog.pg_tables",
            max_rows=10, allowed_schemas={"bi"},
            dialect=PostgresDialect(),
        )


def test_disallowed_schema_blocked_sqlserver():
    with pytest.raises(ValueError):
        guard_sql_or_raise(
            "SELECT * FROM sys.tables",
            max_rows=10, allowed_schemas={"bi"},
            dialect=SqlServerDialect(),
        )


def test_dangerous_function_blocked():
    with pytest.raises(ValueError):
        guard_sql_or_raise(
            "SELECT pg_sleep(5)",
            max_rows=10, allowed_schemas={"bi"},
            dialect=PostgresDialect(),
        )


def test_explain_analyze_blocked():
    with pytest.raises(ValueError):
        guard_sql_or_raise(
            "EXPLAIN ANALYZE SELECT * FROM bi.t",
            max_rows=10, allowed_schemas={"bi"},
            dialect=PostgresDialect(),
        )
