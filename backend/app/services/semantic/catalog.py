"""Catalog loader for the semantic compiler (Phase C1).

Wraps the JSON catalog produced by ``bi_meta.get_catalog()`` (or any
equivalent dict shape) into typed lookups. Pure data — no DB
connections.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, Mapping, Optional

from backend.app.services.semantic.models import Dimension, Metric


_DEFAULT_BASE_VIEW = "bi.vw_fact_sales_line_clean"
_DEFAULT_BASE_ALIAS = "f"


def _items(raw: Any) -> Iterable[Mapping[str, Any]]:
    """Yield dict items from a list-of-dicts; tolerate strings."""
    if isinstance(raw, list):
        for it in raw:
            if isinstance(it, Mapping):
                yield it


class Catalog:
    """Typed view over a bi_meta-style catalog dict."""

    def __init__(
        self,
        metrics: Dict[str, Metric],
        dimensions: Dict[str, Dimension],
        *,
        base_view: str = _DEFAULT_BASE_VIEW,
        base_alias: str = _DEFAULT_BASE_ALIAS,
        schema: Optional[str] = None,
    ) -> None:
        self.metrics = metrics
        self.dimensions = dimensions
        self.base_view = base_view
        self.base_alias = base_alias
        self.schema = schema

    # ---- Lookups ----
    def metric(self, key: str) -> Optional[Metric]:
        return self.metrics.get(key)

    def dimension(self, key: str) -> Optional[Dimension]:
        return self.dimensions.get(key)

    def has_metric(self, key: str) -> bool:
        return key in self.metrics

    def has_dimension(self, key: str) -> bool:
        return key in self.dimensions

    # ---- Constructors ----
    @classmethod
    def from_bi_meta(cls, raw: Mapping[str, Any]) -> "Catalog":
        """Build a Catalog from the JSON shape returned by
        ``bi_meta.get_catalog()``:

            {
              "schema": "bi",
              "base_view": "bi.vw_fact_sales_line_clean",
              "metrics":     [{"key": ..., "agg": ..., "sql": ..., "data_type": ...}, ...],
              "dimensions":  [{"key": ..., "sql": ..., "data_type": ..., "allowed_grouping": ...}, ...],
              "synonyms":    [...]   # ignored by the compiler
            }
        """
        if not isinstance(raw, Mapping):
            raise TypeError("Catalog source must be a mapping")

        metrics: Dict[str, Metric] = {}
        for it in _items(raw.get("metrics")):
            key = str(it.get("key") or it.get("metric_key") or "").strip()
            if not key:
                continue
            metrics[key] = Metric(
                key=key,
                agg=str(it.get("agg") or "sum").lower(),
                sql_expression=str(it.get("sql") or it.get("sql_expression") or "").strip(),
                data_type=str(it.get("data_type") or "numeric"),
            )

        dimensions: Dict[str, Dimension] = {}
        for it in _items(raw.get("dimensions")):
            key = str(it.get("key") or it.get("dim_key") or "").strip()
            if not key:
                continue
            dimensions[key] = Dimension(
                key=key,
                sql_expression=str(it.get("sql") or it.get("sql_expression") or "").strip(),
                data_type=str(it.get("data_type") or "text"),
                allowed_grouping=bool(it.get("allowed_grouping", True)),
            )

        schema = raw.get("schema")
        base_view = str(raw.get("base_view") or _DEFAULT_BASE_VIEW)
        return cls(
            metrics=metrics,
            dimensions=dimensions,
            base_view=base_view,
            base_alias=_DEFAULT_BASE_ALIAS,
            schema=str(schema) if schema else None,
        )
