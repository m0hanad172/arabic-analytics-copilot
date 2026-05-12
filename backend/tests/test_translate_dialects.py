"""Translator + dialect interaction (Phase A).

These tests pin down two things:
1. With the Postgres dialect, translate_arabic_to_sql still produces
   PG-flavoured SQL (LIMIT, ::numeric, ::bigint, NULLS LAST).
2. With the SQL Server dialect, the same questions produce T-SQL that
   contains no PG-only syntax (no ::bigint, no LIMIT, no ILIKE).
"""
import re

from backend.app.db.dialects import PostgresDialect, SqlServerDialect
from backend.app.sqlgen.translate import translate_arabic_to_sql


CATALOG = {
    "bi.fact_sales_line": [
        {"name": "city", "type": "text", "pos": 1},
        {"name": "order_total", "type": "numeric", "pos": 2},
    ],
    "bi.vw_sales_monthly": [
        {"name": "month_start", "type": "date", "pos": 1},
        {"name": "order_year", "type": "int", "pos": 2},
        {"name": "order_month", "type": "int", "pos": 3},
        {"name": "net_sales", "type": "numeric", "pos": 4},
    ],
}


# ----------------------------- Postgres path -----------------------------

class TestTranslatorPostgres:
    pg = PostgresDialect()

    def test_top_n_products_keeps_pg_syntax(self):
        sql, _ = translate_arabic_to_sql(
            "افضل 5 منتجات", CATALOG, max_rows=200, dialect=self.pg
        )
        assert "::numeric" in sql
        assert "::bigint" in sql
        assert "NULLS LAST" in sql
        assert sql.rstrip().endswith("LIMIT 5")

    def test_groupby_city_keeps_pg_syntax(self):
        sql, _ = translate_arabic_to_sql(
            "المبيعات حسب المدينة", CATALOG, max_rows=50, dialect=self.pg
        )
        assert "::numeric" in sql
        assert "::bigint" in sql
        assert sql.rstrip().endswith("LIMIT 50")

    def test_fallback_keeps_pg_limit(self):
        sql, _ = translate_arabic_to_sql(
            "كل البيانات", CATALOG, max_rows=200, dialect=self.pg
        )
        assert "LIMIT 200" in sql

    def test_order_count_groupby_keeps_pg_syntax(self):
        sql, _ = translate_arabic_to_sql(
            "عدد الطلبات حسب المدينة", CATALOG, max_rows=25, dialect=self.pg
        )
        assert "COUNT(*)::bigint" in sql
        assert "LIMIT 25" in sql


# ----------------------------- SQL Server path -----------------------------

class TestTranslatorSqlServer:
    ms = SqlServerDialect()

    def _bans(self, sql: str):
        upper = sql.upper()
        assert "::BIGINT" not in upper, sql
        assert "::NUMERIC" not in upper, sql
        assert "ILIKE" not in upper, sql
        assert not re.search(r"\bLIMIT\s+\d+", upper), sql

    def test_top_n_products_uses_top(self):
        sql, _ = translate_arabic_to_sql(
            "افضل 5 منتجات", CATALOG, max_rows=200, dialect=self.ms
        )
        self._bans(sql)
        assert "TOP (5)" in sql
        assert "COUNT_BIG(*)" in sql
        assert "CAST(" in sql.upper()

    def test_groupby_city_uses_top(self):
        sql, _ = translate_arabic_to_sql(
            "المبيعات حسب المدينة", CATALOG, max_rows=50, dialect=self.ms
        )
        self._bans(sql)
        assert "TOP (50)" in sql

    def test_monthly_uses_top(self):
        sql, _ = translate_arabic_to_sql(
            "صافي المبيعات شهري 2024", CATALOG, max_rows=12, dialect=self.ms
        )
        self._bans(sql)
        assert "TOP (12)" in sql

    def test_fallback_uses_top(self):
        sql, _ = translate_arabic_to_sql(
            "كل البيانات", CATALOG, max_rows=200, dialect=self.ms
        )
        self._bans(sql)
        assert sql.upper().startswith("SELECT TOP (200)")

    def test_order_count_groupby_uses_top(self):
        sql, _ = translate_arabic_to_sql(
            "عدد الطلبات حسب المدينة", CATALOG, max_rows=25, dialect=self.ms
        )
        self._bans(sql)
        assert "TOP (25)" in sql
        assert "COUNT_BIG(*)" in sql
