"""Python semantic compiler unit tests (Phase C1).

No database connection required.
"""
import re

import pytest

from backend.app.db.dialects import PostgresDialect, SqlServerDialect
from backend.app.services.semantic import (
    Catalog,
    EmptyPlanError,
    InvalidFilterValueError,
    UnknownDimensionError,
    UnknownMetricError,
    UnsupportedDimensionForBackend,
    UnsupportedFilterOpError,
    compile_plan,
)


# ----- Catalog mirrors the live bi_meta data -----
CATALOG_RAW = {
    "schema": "bi",
    "base_view": "bi.vw_fact_sales_line_clean",
    "metrics": [
        {"key": "net_sales", "agg": "sum", "sql": "sum(f.order_total::numeric)", "data_type": "numeric"},
        {"key": "gross_sales", "agg": "sum", "sql": "sum(f.sub_total::numeric)", "data_type": "numeric"},
        {"key": "discount_amount", "agg": "sum", "sql": "sum(f.discount_amount::numeric)", "data_type": "numeric"},
        {"key": "gross_profit", "agg": "sum", "sql": "sum(f.gross_profit::numeric)", "data_type": "numeric"},
        {"key": "line_count", "agg": "count", "sql": "count(*)::bigint", "data_type": "bigint"},
        {"key": "order_count", "agg": "count", "sql": "COUNT(*)::bigint", "data_type": "integer"},
        {"key": "avg_ship_delay_days", "agg": "avg", "sql": "avg(f.ship_delay_days::numeric)", "data_type": "numeric"},
    ],
    "dimensions": [
        {"key": "city", "sql": "f.city", "data_type": "text"},
        {"key": "state", "sql": "f.state", "data_type": "text"},
        {"key": "product_category", "sql": "f.product_category", "data_type": "text"},
        {"key": "product_name", "sql": "f.product_name", "data_type": "text"},
        {"key": "ship_mode", "sql": "f.ship_mode", "data_type": "text"},
        {"key": "order_year", "sql": "extract(year from f.order_date_d)::int", "data_type": "integer"},
        {"key": "order_quarter", "sql": "extract(quarter from f.order_date_d)::int", "data_type": "integer"},
    ],
}
CATALOG = Catalog.from_bi_meta(CATALOG_RAW)


# ===========================================================================
# Postgres dialect
# ===========================================================================
class TestCompilerPostgres:
    pg = PostgresDialect()

    def test_metric_only(self):
        sql = compile_plan({"metrics": ["net_sales"], "limit": 10}, CATALOG, dialect=self.pg)
        assert sql.endswith(";")
        assert sql.count(";") == 1
        assert 'sum(f.order_total::numeric) AS "net_sales"' in sql
        assert "FROM bi.vw_fact_sales_line_clean f" in sql
        assert "WHERE 1=1" in sql
        assert "GROUP BY" not in sql
        assert sql.rstrip(";").rstrip().endswith("LIMIT 10")

    def test_metric_and_dimension(self):
        plan = {
            "metrics": ["net_sales"],
            "dimensions": ["city"],
            "sort": [{"field": "net_sales", "dir": "desc"}],
            "limit": 5,
        }
        sql = compile_plan(plan, CATALOG, dialect=self.pg)
        assert 'f.city AS "city"' in sql
        assert 'sum(f.order_total::numeric) AS "net_sales"' in sql
        assert "GROUP BY f.city" in sql
        assert 'ORDER BY "net_sales" DESC' in sql
        assert sql.rstrip(";").rstrip().endswith("LIMIT 5")

    def test_order_count_uses_pg_bigint(self):
        sql = compile_plan(
            {"metrics": ["order_count"], "dimensions": ["city"], "limit": 25},
            CATALOG, dialect=self.pg,
        )
        # PG keeps the catalog expression byte-identical.
        assert 'COUNT(*)::bigint AS "order_count"' in sql

    def test_filters_emitted(self):
        plan = {
            "metrics": ["net_sales"],
            "dimensions": ["city"],
            "filters": [
                {"field": "city", "op": "=", "value": "Sydney"},
                {"field": "state", "op": "in", "value": ["NSW", "VIC"]},
                {"field": "product_category", "op": "ilike", "value": "%tech%"},
            ],
            "limit": 50,
        }
        sql = compile_plan(plan, CATALOG, dialect=self.pg)
        assert "AND f.city = 'Sydney'" in sql
        assert "AND f.state IN ('NSW', 'VIC')" in sql
        assert "AND f.product_category ILIKE '%tech%'" in sql

    def test_between_filter(self):
        plan = {
            "metrics": ["net_sales"],
            "filters": [{"field": "order_year", "op": "between", "value": [2023, 2024]}],
        }
        sql = compile_plan(plan, CATALOG, dialect=self.pg)
        assert "BETWEEN 2023 AND 2024" in sql

    def test_limit_clamping(self):
        # below min -> default 500
        sql = compile_plan({"metrics": ["net_sales"], "limit": 0}, CATALOG, dialect=self.pg)
        assert sql.rstrip(";").rstrip().endswith("LIMIT 500")
        # above max -> 5000
        sql = compile_plan({"metrics": ["net_sales"], "limit": 10_000}, CATALOG, dialect=self.pg)
        assert sql.rstrip(";").rstrip().endswith("LIMIT 5000")
        # missing -> default 500
        sql = compile_plan({"metrics": ["net_sales"]}, CATALOG, dialect=self.pg)
        assert sql.rstrip(";").rstrip().endswith("LIMIT 500")

    def test_quote_escaping(self):
        sql = compile_plan(
            {
                "metrics": ["net_sales"],
                "filters": [{"field": "city", "op": "=", "value": "O'Brien"}],
            },
            CATALOG, dialect=self.pg,
        )
        assert "AND f.city = 'O''Brien'" in sql

    def test_empty_in_compiles_to_false_predicate(self):
        sql = compile_plan(
            {"metrics": ["net_sales"], "filters": [{"field": "city", "op": "in", "value": []}]},
            CATALOG, dialect=self.pg,
        )
        assert "AND 1=0" in sql


# ===========================================================================
# SQL Server dialect
# ===========================================================================
class TestCompilerSqlServer:
    ms = SqlServerDialect()

    def _bans(self, sql: str):
        upper = sql.upper()
        assert "::BIGINT" not in upper, sql
        assert "::NUMERIC" not in upper, sql
        assert "ILIKE" not in upper, sql
        assert not re.search(r"\bLIMIT\s+\d+", upper), sql

    def test_metric_only_uses_top(self):
        sql = compile_plan({"metrics": ["net_sales"], "limit": 10}, CATALOG, dialect=self.ms)
        self._bans(sql)
        assert sql.startswith("SELECT TOP (10) ")
        assert "CAST(SUM(f.order_total) AS NUMERIC(38, 6)) AS [net_sales]" in sql

    def test_order_count_uses_count_big(self):
        sql = compile_plan(
            {"metrics": ["order_count"], "dimensions": ["city"], "limit": 25},
            CATALOG, dialect=self.ms,
        )
        self._bans(sql)
        assert "COUNT_BIG(*) AS [order_count]" in sql
        assert "TOP (25)" in sql

    def test_line_count_uses_count_big(self):
        # line_count metric also has agg=count and PG sql `count(*)::bigint`.
        sql = compile_plan(
            {"metrics": ["line_count"]}, CATALOG, dialect=self.ms,
        )
        self._bans(sql)
        assert "COUNT_BIG(*) AS [line_count]" in sql

    def test_avg_metric_uses_cast(self):
        sql = compile_plan(
            {"metrics": ["avg_ship_delay_days"]}, CATALOG, dialect=self.ms,
        )
        self._bans(sql)
        assert "CAST(AVG(f.ship_delay_days) AS NUMERIC(38, 6))" in sql

    def test_ilike_becomes_like(self):
        sql = compile_plan(
            {
                "metrics": ["net_sales"],
                "filters": [{"field": "city", "op": "ilike", "value": "%syd%"}],
            },
            CATALOG, dialect=self.ms,
        )
        self._bans(sql)
        assert "AND f.city LIKE '%syd%'" in sql

    def test_pg_only_dimension_rejected_for_sqlserver(self):
        with pytest.raises(UnsupportedDimensionForBackend):
            compile_plan(
                {"metrics": ["net_sales"], "dimensions": ["order_year"]},
                CATALOG, dialect=self.ms,
            )

    def test_tsql_date_dimensions_pass_through(self):
        """Phase C3: when the catalog already stores T-SQL date
        expressions (DATEPART / DATEFROMPARTS), the compiler must let
        them through unchanged on SQL Server."""
        tsql_catalog = Catalog.from_bi_meta({
            "schema": "bi",
            "base_view": "bi.vw_fact_sales_line_clean",
            "metrics": [
                {"key": "net_sales", "agg": "sum", "sql": "sum(f.order_total)"},
            ],
            "dimensions": [
                {"key": "order_year", "sql": "DATEPART(year, f.order_date_d)"},
                {"key": "order_quarter", "sql": "DATEPART(quarter, f.order_date_d)"},
                {"key": "order_month", "sql": "DATEPART(month, f.order_date_d)"},
                {"key": "month_start",
                 "sql": "DATEFROMPARTS(YEAR(f.order_date_d), MONTH(f.order_date_d), 1)"},
            ],
        })
        for dim, expected in [
            ("order_year", "DATEPART(year, f.order_date_d) AS [order_year]"),
            ("order_quarter", "DATEPART(quarter, f.order_date_d) AS [order_quarter]"),
            ("order_month", "DATEPART(month, f.order_date_d) AS [order_month]"),
            ("month_start",
             "DATEFROMPARTS(YEAR(f.order_date_d), MONTH(f.order_date_d), 1) AS [month_start]"),
        ]:
            sql = compile_plan(
                {"metrics": ["net_sales"], "dimensions": [dim], "limit": 5},
                tsql_catalog, dialect=self.ms,
            )
            self._bans(sql)
            assert expected in sql, sql

    def test_groupby_simple_dim(self):
        sql = compile_plan(
            {"metrics": ["net_sales"], "dimensions": ["city"], "limit": 5},
            CATALOG, dialect=self.ms,
        )
        self._bans(sql)
        assert sql.startswith("SELECT TOP (5) ")
        assert "f.city AS [city]" in sql
        assert "GROUP BY f.city" in sql

    def test_single_trailing_semicolon(self):
        sql = compile_plan({"metrics": ["net_sales"]}, CATALOG, dialect=self.ms)
        assert sql.endswith(";")
        assert sql.count(";") == 1


# ===========================================================================
# Validation errors
# ===========================================================================
def test_unknown_metric_raises():
    with pytest.raises(UnknownMetricError):
        compile_plan({"metrics": ["nope"]}, CATALOG, dialect=PostgresDialect())


def test_unknown_dimension_raises():
    with pytest.raises(UnknownDimensionError):
        compile_plan(
            {"metrics": ["net_sales"], "dimensions": ["nope"]},
            CATALOG, dialect=PostgresDialect(),
        )


def test_unknown_filter_field_raises():
    with pytest.raises(UnknownDimensionError):
        compile_plan(
            {"metrics": ["net_sales"],
             "filters": [{"field": "nope", "op": "=", "value": "x"}]},
            CATALOG, dialect=PostgresDialect(),
        )


def test_empty_plan_raises():
    with pytest.raises(EmptyPlanError):
        compile_plan({}, CATALOG, dialect=PostgresDialect())


def test_unsupported_op_raises():
    with pytest.raises(UnsupportedFilterOpError):
        compile_plan(
            {"metrics": ["net_sales"],
             "filters": [{"field": "city", "op": "regex", "value": ".*"}]},
            CATALOG, dialect=PostgresDialect(),
        )


def test_between_invalid_value_raises():
    with pytest.raises(InvalidFilterValueError):
        compile_plan(
            {"metrics": ["net_sales"],
             "filters": [{"field": "city", "op": "between", "value": "bad"}]},
            CATALOG, dialect=PostgresDialect(),
        )


def test_in_with_non_array_raises():
    with pytest.raises(InvalidFilterValueError):
        compile_plan(
            {"metrics": ["net_sales"],
             "filters": [{"field": "city", "op": "in", "value": "not a list"}]},
            CATALOG, dialect=PostgresDialect(),
        )
