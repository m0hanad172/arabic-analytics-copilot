"""Catalog loader tests (Phase C1)."""
from backend.app.services.semantic import Catalog, Dimension, Metric


# Trimmed copy of the real bi_meta.get_catalog() output.
SAMPLE = {
    "schema": "bi",
    "base_view": "bi.vw_fact_sales_line_clean",
    "metrics": [
        {"key": "net_sales", "agg": "sum", "sql": "sum(f.order_total::numeric)", "data_type": "numeric"},
        {"key": "order_count", "agg": "count", "sql": "COUNT(*)::bigint", "data_type": "integer"},
        {"key": "discounts", "agg": "sum", "sql": "sum(f.discount_amount::numeric)", "data_type": "numeric"},
        # malformed entries should be skipped silently:
        {"agg": "sum", "sql": "..."},  # no key
        "garbage",
    ],
    "dimensions": [
        {"key": "city", "sql": "f.city", "data_type": "text", "allowed_grouping": True},
        {"key": "order_year", "sql": "extract(year from f.order_date_d)::int",
         "data_type": "integer", "allowed_grouping": True},
    ],
    "synonyms": [{"term": "city", "type": "dimension", "key": "city"}],
}


def test_catalog_from_bi_meta_indexes_metrics_and_dimensions():
    cat = Catalog.from_bi_meta(SAMPLE)
    assert cat.schema == "bi"
    assert cat.base_view == "bi.vw_fact_sales_line_clean"
    assert cat.base_alias == "f"

    assert isinstance(cat.metric("net_sales"), Metric)
    assert cat.metric("net_sales").agg == "sum"
    assert cat.metric("net_sales").sql_expression == "sum(f.order_total::numeric)"

    assert cat.metric("order_count").agg == "count"
    assert cat.metric("order_count").data_type == "integer"

    assert isinstance(cat.dimension("city"), Dimension)
    assert cat.dimension("city").sql_expression == "f.city"

    assert cat.has_metric("net_sales")
    assert cat.has_dimension("city")
    assert not cat.has_metric("nope")
    assert not cat.has_dimension("nope")


def test_catalog_skips_malformed_entries():
    cat = Catalog.from_bi_meta(SAMPLE)
    # Only well-formed metrics survive (3 of the 5 raw entries).
    assert set(cat.metrics.keys()) == {"net_sales", "order_count", "discounts"}


def test_catalog_accepts_alternate_keys():
    raw = {
        "metrics": [
            {"metric_key": "alt_metric", "agg": "sum", "sql_expression": "sum(f.x::numeric)"}
        ],
        "dimensions": [
            {"dim_key": "alt_dim", "sql_expression": "f.x", "data_type": "text"}
        ],
    }
    cat = Catalog.from_bi_meta(raw)
    assert cat.has_metric("alt_metric")
    assert cat.has_dimension("alt_dim")
