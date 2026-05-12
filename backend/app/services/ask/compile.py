"""Compiler dispatch for /ask (Phase C2).

Single entry point that decides between the legacy PostgreSQL path
(``bi_meta.compile_query``) and the in-process Python compiler added
in Phase C1, based on ``settings.compiler_backend``.

The dispatch never connects to the database itself for the Python
path — that is required by C1 — and never falls back to PostgreSQL
silently. Callers see a clear error when the requested backend cannot
be used.
"""
from __future__ import annotations

import json
from typing import Any, Optional, Tuple

from backend.app.core.config import settings
from backend.app.db.adapter import (
    BackendNotSupportedError,
    controlled_backend_error_message,
    is_sqlserver,
    pg_fetchval,
)
from backend.app.db.dialects import SqlDialect, get_dialect
from backend.app.services.semantic import Catalog, compile_plan


_DB_COMPILER = "db"
_PYTHON_COMPILER = "python"


def active_compiler_backend() -> str:
    """Resolve the active compiler backend with safe fallback."""
    raw = (getattr(settings, "compiler_backend", None) or _DB_COMPILER).strip().lower()
    if raw in (_DB_COMPILER, _PYTHON_COMPILER):
        return raw
    # Unknown value -> safer default ("db" preserves current behaviour).
    return _DB_COMPILER


async def compile_for_request(
    plan: dict,
    catalog: dict,
    *,
    dialect: Optional[SqlDialect] = None,
) -> Tuple[str, str]:
    """Compile ``plan`` to SQL using the active compiler backend.

    Returns ``(sql, compiler_backend)`` where ``compiler_backend`` is
    one of ``"db"`` / ``"python"``.

    - ``db`` path runs ``bi_meta.compile_query`` on PostgreSQL. Raises
      :class:`BackendNotSupportedError` when the active DB backend is
      not PostgreSQL.
    - ``python`` path runs the C1 in-process compiler against the
      catalog and the active dialect. Never touches the database.
    """
    backend = active_compiler_backend()

    if backend == _PYTHON_COMPILER:
        d = dialect if dialect is not None else get_dialect()
        cat = Catalog.from_bi_meta(catalog or {})
        sql = compile_plan(plan, cat, dialect=d)
        return sql, _PYTHON_COMPILER

    # Legacy DB path
    if is_sqlserver():
        raise BackendNotSupportedError(
            "COMPILER_BACKEND=db requires PostgreSQL. "
            + controlled_backend_error_message()
            + " Set COMPILER_BACKEND=python to use the in-process compiler."
        )
    compiled = await pg_fetchval(
        "SELECT bi_meta.compile_query($1::jsonb);",
        json.dumps(plan, ensure_ascii=False),
    )
    if not compiled or not str(compiled).strip():
        raise RuntimeError("bi_meta.compile_query returned empty SQL.")
    return str(compiled), _DB_COMPILER


__all__ = [
    "active_compiler_backend",
    "compile_for_request",
]
