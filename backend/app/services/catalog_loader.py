"""Portable catalog loader (Phase C3).

Returns the same JSON shape that ``bi_meta.get_catalog()`` produces on
PostgreSQL, regardless of which database backend is active.

- On PostgreSQL: delegates to the existing path (``bi_meta.get_catalog``
  via ``runner._db_fetchval``). Tests that monkey-patch ``runner``
  remain valid.
- On SQL Server: reads ``bi_meta.metrics`` / ``bi_meta.dimensions`` /
  ``bi_meta.synonyms`` directly via SQLAlchemy ``AsyncSession``. No
  PostgreSQL-specific syntax is used (no ``::jsonb``, no ``$N``
  placeholders, no ``ON CONFLICT``).

This module is intentionally small: it only owns the catalog read path.
Cache and log writes remain in ``services/ask/runner.py``.
"""
from __future__ import annotations

from typing import Any, Dict, List

from sqlalchemy import text

from backend.app.db.adapter import is_sqlserver


# Default base view the compiler resolves to when the catalog row does
# not override it. Mirrors the PG bi_meta.get_catalog() default.
_DEFAULT_BASE_VIEW = "bi.vw_fact_sales_line_clean"


async def load_sqlserver_catalog(schema: str = "bi") -> Dict[str, Any]:
    """Build the catalog JSON object for an active SQL Server backend.

    Same shape as ``bi_meta.get_catalog()``:

    ``{ "schema": str, "base_view": str,
       "metrics": [...], "dimensions": [...], "synonyms": [...] }``
    """
    # Imported lazily so the module is import-safe in tests that never
    # touch SQLAlchemy.
    from backend.app.db.session import SessionLocal

    async with SessionLocal() as session:
        metrics_rows = (
            await session.execute(
                text(
                    "SELECT metric_key, display_name_ar, display_name_en, agg, "
                    "       sql_expression, data_type, format_hint "
                    "FROM bi_meta.metrics ORDER BY metric_key"
                )
            )
        ).mappings().all()

        dimensions_rows = (
            await session.execute(
                text(
                    "SELECT dim_key, display_name_ar, display_name_en, "
                    "       sql_expression, data_type, allowed_grouping "
                    "FROM bi_meta.dimensions ORDER BY dim_key"
                )
            )
        ).mappings().all()

        synonyms_rows = (
            await session.execute(
                text(
                    "SELECT term, maps_to_type, maps_to_key "
                    "FROM bi_meta.synonyms ORDER BY term"
                )
            )
        ).mappings().all()

    return _build_catalog_dict(
        schema=schema,
        metrics_rows=metrics_rows,
        dimensions_rows=dimensions_rows,
        synonyms_rows=synonyms_rows,
    )


def _build_catalog_dict(
    *,
    schema: str,
    metrics_rows: List[Dict[str, Any]],
    dimensions_rows: List[Dict[str, Any]],
    synonyms_rows: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Pure assembly: row mappings -> bi_meta.get_catalog() JSON shape.

    Factored out for unit tests so they don't need a SQLAlchemy session.
    """
    return {
        "schema": schema,
        "base_view": _DEFAULT_BASE_VIEW,
        "metrics": [
            {
                "key": r["metric_key"],
                "name_ar": r.get("display_name_ar"),
                "name_en": r.get("display_name_en"),
                "agg": r.get("agg"),
                "sql": r.get("sql_expression"),
                "data_type": r.get("data_type"),
                "format": r.get("format_hint"),
            }
            for r in metrics_rows
        ],
        "dimensions": [
            {
                "key": r["dim_key"],
                "name_ar": r.get("display_name_ar"),
                "name_en": r.get("display_name_en"),
                "sql": r.get("sql_expression"),
                "data_type": r.get("data_type"),
                "allowed_grouping": bool(r.get("allowed_grouping", True)),
            }
            for r in dimensions_rows
        ],
        "synonyms": [
            {
                "term": r["term"],
                "type": r.get("maps_to_type"),
                "key": r.get("maps_to_key"),
            }
            for r in synonyms_rows
        ],
    }


async def load_catalog_for_active_backend(schema: str = "bi") -> Dict[str, Any]:
    """Backend-aware catalog loader.

    Returns ``bi_meta.get_catalog()``-shaped JSON regardless of backend.
    On PostgreSQL the loader delegates to the existing runner path so
    behaviour is byte-identical to pre-C3.
    """
    if is_sqlserver():
        return await load_sqlserver_catalog(schema)

    # Local import to avoid a circular import with runner.
    from backend.app.services.ask.runner import _db_fetchval

    try:
        cat = await _db_fetchval("SELECT bi_meta.get_catalog($1)::jsonb;", schema)
    except Exception:
        cat = await _db_fetchval("SELECT bi_meta.get_catalog();")
    if not isinstance(cat, dict):
        raise RuntimeError("Catalog is empty or not a JSON object.")
    return cat


__all__ = [
    "load_catalog_for_active_backend",
    "load_sqlserver_catalog",
    "_build_catalog_dict",
]
