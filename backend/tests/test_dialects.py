"""Tests for the SQL dialect layer (Phase A)."""
import pytest

from backend.app.db.dialects import (
    PostgresDialect,
    SqlServerDialect,
    get_dialect,
)


# ----------------------------- Resolver -----------------------------

def test_get_dialect_resolves_aliases():
    assert isinstance(get_dialect("postgres"), PostgresDialect)
    assert isinstance(get_dialect("postgresql"), PostgresDialect)
    assert isinstance(get_dialect("pg"), PostgresDialect)
    assert isinstance(get_dialect("sqlserver"), SqlServerDialect)
    assert isinstance(get_dialect("mssql"), SqlServerDialect)
    assert isinstance(get_dialect("tsql"), SqlServerDialect)


def test_get_dialect_unknown_raises():
    with pytest.raises(ValueError):
        get_dialect("oracle")


# ----------------------------- Postgres -----------------------------

class TestPostgresDialect:
    pg = PostgresDialect()

    def test_limit_clause(self):
        assert self.pg.limit_clause(5) == "LIMIT 5"

    def test_apply_limit_appends(self):
        out = self.pg.apply_limit("SELECT * FROM bi.t", 10)
        assert out.endswith("LIMIT 10")

    def test_apply_limit_idempotent(self):
        once = self.pg.apply_limit("SELECT * FROM bi.t", 10)
        twice = self.pg.apply_limit(once, 10)
        assert twice.lower().count("limit ") == 1

    def test_bigint_count(self):
        assert self.pg.bigint_count() == "COUNT(*)::bigint"

    def test_cast_numeric(self):
        assert self.pg.cast_numeric("SUM(x)") == "SUM(x)::numeric"

    def test_quote_ident(self):
        assert self.pg.quote_ident("col") == '"col"'
        assert self.pg.quote_ident('a"b') == '"a""b"'

    def test_ilike(self):
        assert self.pg.ilike("name", "'%abc%'") == "name ILIKE '%abc%'"

    def test_now(self):
        assert self.pg.now() == "now()"

    def test_nulls_last(self):
        assert self.pg.nulls_last("DESC") == "DESC NULLS LAST"
        assert self.pg.nulls_last("asc") == "ASC NULLS LAST"

    def test_set_statement_timeout(self):
        assert self.pg.set_statement_timeout(8000) == "SET statement_timeout = 8000"


# ----------------------------- SQL Server -----------------------------

class TestSqlServerDialect:
    ms = SqlServerDialect()

    def test_limit_clause(self):
        assert self.ms.limit_clause(5) == "TOP (5)"

    def test_apply_limit_injects_top(self):
        out = self.ms.apply_limit("SELECT col FROM bi.t", 7)
        assert out.startswith("SELECT TOP (7) col FROM bi.t")
        assert "LIMIT" not in out.upper()

    def test_apply_limit_handles_distinct(self):
        out = self.ms.apply_limit("SELECT DISTINCT col FROM bi.t", 3)
        assert out.startswith("SELECT DISTINCT TOP (3) col FROM bi.t")

    def test_apply_limit_idempotent(self):
        once = self.ms.apply_limit("SELECT * FROM bi.t", 10)
        twice = self.ms.apply_limit(once, 10)
        assert twice.upper().count("TOP (") == 1

    def test_bigint_count(self):
        assert self.ms.bigint_count() == "COUNT_BIG(*)"

    def test_cast_numeric_no_pg_cast(self):
        out = self.ms.cast_numeric("SUM(x)")
        assert "::" not in out
        assert out.upper().startswith("CAST(SUM(X) AS NUMERIC")

    def test_quote_ident(self):
        assert self.ms.quote_ident("col") == "[col]"
        assert self.ms.quote_ident("a]b") == "[a]]b]"

    def test_ilike_uses_like(self):
        out = self.ms.ilike("name", "'%abc%'")
        assert "ILIKE" not in out.upper()
        assert out == "name LIKE '%abc%'"

    def test_now(self):
        assert self.ms.now() == "SYSUTCDATETIME()"

    def test_nulls_last_returns_direction_only(self):
        assert "NULLS" not in self.ms.nulls_last("DESC").upper()

    def test_set_statement_timeout_returns_none(self):
        assert self.ms.set_statement_timeout(8000) is None


# ----------------------------- Cross-dialect sanity -----------------------------

def test_sqlserver_output_has_no_postgres_isms():
    ms = SqlServerDialect()
    fragments = [
        ms.limit_clause(5),
        ms.bigint_count(),
        ms.cast_numeric("SUM(x)"),
        ms.apply_limit("SELECT * FROM bi.t", 5),
        ms.ilike("c", "'%a%'"),
    ]
    blob = " | ".join(fragments)
    upper = blob.upper()
    assert "::BIGINT" not in upper
    assert "::NUMERIC" not in upper
    assert "ILIKE" not in upper
    assert "LIMIT " not in upper
