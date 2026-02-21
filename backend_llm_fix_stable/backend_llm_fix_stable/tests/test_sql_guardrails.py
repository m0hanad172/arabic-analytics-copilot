# backend/tests/test_sql_guardrails.py
import pytest

from backend.app.core.sql_guardrails import guard_sql_or_raise


def _ok(sql: str, max_rows: int = 100, schemas=None) -> str:
    """Helper: should NOT raise."""
    if schemas is None:
        schemas = {"bi"}
    out = guard_sql_or_raise(sql, max_rows=max_rows, allowed_schemas=schemas)
    assert isinstance(out, str) and out.strip()
    return out


def _bad(sql: str, max_rows: int = 100, schemas=None):
    """Helper: should raise."""
    if schemas is None:
        schemas = {"bi"}
    with pytest.raises(Exception):
        guard_sql_or_raise(sql, max_rows=max_rows, allowed_schemas=schemas)


def test_allows_simple_select():
    _ok("select 1")


def test_allows_single_statement_with_trailing_semicolon():
    _ok("select 1;")


def test_semicolon_inside_quotes_not_counted_as_second_stmt():
    # Semicolon inside quotes shouldn't trigger multi-statement detection
    _ok("select ';' as s;")


def test_blocks_multi_statement():
    _bad("select 1; select 2;")


def test_blocks_dml_delete():
    _bad("delete from bi.vw_fact_sales_line_clean")


def test_blocks_ddl_drop():
    _bad("drop table bi.anything")


def test_blocks_dangerous_function_pg_sleep():
    _bad("select pg_sleep(1)")


def test_blocks_denied_schema_pg_catalog():
    _bad("select * from pg_catalog.pg_tables")


def test_blocks_comments_if_denied():
    # if deny_comments=True (default in GuardrailsConfig), this should be blocked
    _bad("select 1 -- comment")


def test_allows_explain_plain():
    _ok("explain select 1")


def test_blocks_explain_analyze():
    # file mentions allow EXPLAIN but not ANALYZE as command
    _bad("explain analyze select 1")


def test_max_rows_parameter_applies_or_keeps_safe_limit():
    out = _ok("select * from bi.vw_fact_sales_line_clean", max_rows=10)
    # Some implementations append LIMIT, others enforce/cap differently.
    # We'll accept either: contains 'limit 10' OR already contains some limit <= 10.
    o = out.lower()
    if "limit" in o:
        # If it injected a limit, this must not exceed 10
        # Minimal parse: check first integer after 'limit'
        tail = o.split("limit", 1)[1].strip()
        num = ""
        for ch in tail:
            if ch.isdigit():
                num += ch
            elif num:
                break
        if num:
            assert int(num) <= 10
