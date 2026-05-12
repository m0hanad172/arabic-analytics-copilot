"""Compiler exceptions (Phase C1).

Raised by ``compile_plan`` and the catalog loader. All inherit from
:class:`CompilerError` so callers can wrap a single ``except`` and turn
them into a 400-class HTTP response in Phase C2.
"""
from __future__ import annotations


class CompilerError(ValueError):
    """Base class for every compiler-side rejection."""


class UnknownMetricError(CompilerError):
    """Plan referenced a metric key not in the catalog."""


class UnknownDimensionError(CompilerError):
    """Plan referenced a dimension key not in the catalog."""


class UnsupportedFilterOpError(CompilerError):
    """Plan used an operator the compiler does not implement."""


class InvalidFilterValueError(CompilerError):
    """Filter value shape did not match the operator (e.g. BETWEEN
    requires a 2-element array)."""


class EmptyPlanError(CompilerError):
    """Plan had no metrics and no dimensions."""


class UnsupportedDimensionForBackend(CompilerError):
    """Dimension catalog entry uses SQL the active dialect cannot emit
    yet (e.g. ``date_trunc`` / ``extract`` on SQL Server)."""
