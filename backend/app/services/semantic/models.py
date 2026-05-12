"""Typed data structures for the semantic compiler (Phase C1).

These mirror the shape of plans coming from /ask and catalogs coming
from ``bi_meta.get_catalog()``. We keep the structures small and
immutable; the compiler never mutates them in place.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional


# ---------------------------------------------------------------------------
# Catalog primitives
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Metric:
    key: str
    agg: str  # "sum" | "avg" | "count"
    sql_expression: str  # raw expression as stored in bi_meta.metrics
    data_type: str = "numeric"


@dataclass(frozen=True)
class Dimension:
    key: str
    sql_expression: str  # raw expression as stored in bi_meta.dimensions
    data_type: str = "text"
    allowed_grouping: bool = True


# ---------------------------------------------------------------------------
# Plan primitives
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Filter:
    field: str
    op: str  # "=", "!=", ">", ">=", "<", "<=", "ilike", "between", "in"
    value: Any


@dataclass(frozen=True)
class Sort:
    field: str
    dir: str = "desc"  # "asc" | "desc"


@dataclass(frozen=True)
class Plan:
    metrics: List[str] = field(default_factory=list)
    dimensions: List[str] = field(default_factory=list)
    filters: List[Filter] = field(default_factory=list)
    sort: List[Sort] = field(default_factory=list)
    limit: Optional[int] = None

    @classmethod
    def from_dict(cls, raw: dict) -> "Plan":
        if not isinstance(raw, dict):
            raise TypeError("Plan must be a dict")

        def _strs(xs: Any) -> List[str]:
            if not isinstance(xs, list):
                return []
            return [str(x) for x in xs if isinstance(x, (str, int, float))]

        filters: List[Filter] = []
        for f in raw.get("filters") or []:
            if not isinstance(f, dict):
                continue
            filters.append(
                Filter(
                    field=str(f.get("field") or ""),
                    op=str(f.get("op") or "").lower(),
                    value=f.get("value"),
                )
            )

        sort: List[Sort] = []
        for s in raw.get("sort") or []:
            if not isinstance(s, dict):
                continue
            d = (s.get("dir") or "desc").lower()
            sort.append(
                Sort(
                    field=str(s.get("field") or ""),
                    dir="asc" if d == "asc" else "desc",
                )
            )

        limit_raw = raw.get("limit")
        try:
            limit_val: Optional[int] = int(limit_raw) if limit_raw is not None else None
        except (TypeError, ValueError):
            limit_val = None

        return cls(
            metrics=_strs(raw.get("metrics")),
            dimensions=_strs(raw.get("dimensions")),
            filters=filters,
            sort=sort,
            limit=limit_val,
        )
