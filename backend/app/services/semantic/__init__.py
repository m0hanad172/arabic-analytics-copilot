"""In-process semantic compiler (Phase C1).

Public surface kept small on purpose: callers should rely on
:func:`compile_plan` and the typed exceptions in :mod:`errors`.
"""
from backend.app.services.semantic.catalog import Catalog
from backend.app.services.semantic.compiler import compile_plan
from backend.app.services.semantic.errors import (
    CompilerError,
    EmptyPlanError,
    InvalidFilterValueError,
    UnknownDimensionError,
    UnknownMetricError,
    UnsupportedDimensionForBackend,
    UnsupportedFilterOpError,
)
from backend.app.services.semantic.models import (
    Dimension,
    Filter,
    Metric,
    Plan,
    Sort,
)

__all__ = [
    "Catalog",
    "compile_plan",
    "CompilerError",
    "EmptyPlanError",
    "InvalidFilterValueError",
    "UnknownDimensionError",
    "UnknownMetricError",
    "UnsupportedDimensionForBackend",
    "UnsupportedFilterOpError",
    "Dimension",
    "Filter",
    "Metric",
    "Plan",
    "Sort",
]
