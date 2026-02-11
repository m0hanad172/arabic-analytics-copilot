from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.introspect import load_schema_catalog

logger = logging.getLogger(__name__)

CatalogT = Dict[str, List[Dict[str, Any]]]

_catalog: Optional[CatalogT] = None
_catalog_source: str = "unknown"


def _item_key(it: Any) -> str:
    if isinstance(it, dict):
        return str(it.get("key") or it.get("name") or it.get("metric_key") or it.get("dim_key") or "").strip()
    return str(it).strip()


def _as_list_of_dict(items: Any) -> List[Dict[str, Any]]:
    """
    Normalize catalog bucket to list[{"key":..., "label":...}] as a safe minimum.
    Accepts list[str] or list[dict].
    """
    out: List[Dict[str, Any]] = []
    if not isinstance(items, list):
        return out

    for it in items:
        if isinstance(it, dict):
            k = _item_key(it)
            if not k:
                continue
            label = it.get("label") or it.get("display_name_ar") or it.get("display_name_en") or k
            out.append({"key": k, "label": str(label)})
        else:
            k = _item_key(it)
            if k:
                out.append({"key": k, "label": k})
    return out


def _looks_like_catalog(obj: Any) -> bool:
    if not isinstance(obj, dict):
        return False
    return ("metrics" in obj) and ("dimensions" in obj)


def _augment_catalog(catalog: dict) -> CatalogT:
    """
    Keep it consistent with /ask: ensure some defaults exist.
    """
    metrics = _as_list_of_dict(catalog.get("metrics"))
    dims = _as_list_of_dict(catalog.get("dimensions"))

    def ensure(bucket: List[Dict[str, Any]], key: str) -> None:
        if key not in {x.get("key") for x in bucket if isinstance(x, dict)}:
            bucket.append({"key": key, "label": key})

    # Ensure key dims
    ensure(dims, "order_year")
    ensure(dims, "order_quarter")

    # Ensure key metrics
    ensure(metrics, "discount_amount")

    return {"metrics": metrics, "dimensions": dims}


async def _load_catalog_from_db(session: AsyncSession) -> Optional[dict]:
    """
    Try bi_meta.get_catalog() first, then the optional signature with schema arg.
    Works even if DB returns JSON as text.
    """
    try:
        res = await session.execute(text("SELECT bi_meta.get_catalog();"))
        val = res.scalar_one_or_none()
    except Exception:
        val = None

    if not val:
        try:
            res = await session.execute(text("SELECT bi_meta.get_catalog(:schema)::jsonb;"), {"schema": "bi"})
            val = res.scalar_one_or_none()
        except Exception:
            val = None

    if not val:
        return None

    if isinstance(val, str):
        try:
            val = json.loads(val)
        except Exception:
            return None

    return val if isinstance(val, dict) else None


async def _load_catalog(session: AsyncSession) -> CatalogT:
    global _catalog_source

    # 1) DB function source (preferred to match /ask)
    db_cat = await _load_catalog_from_db(session)
    if db_cat and _looks_like_catalog(db_cat):
        _catalog_source = "db_function"
        cat = _augment_catalog(db_cat)
        logger.info("Catalog loaded from DB function bi_meta.get_catalog().")
        return cat

    # 2) Introspection fallback
    intro = await load_schema_catalog(session)
    _catalog_source = "introspect"
    logger.warning("Catalog loaded from introspection (DB function unavailable or invalid).")
    return _augment_catalog(intro)


async def get_catalog(session: AsyncSession) -> CatalogT:
    global _catalog
    if _catalog is None:
        _catalog = await _load_catalog(session)
    return _catalog


async def refresh_catalog(session: AsyncSession) -> CatalogT:
    global _catalog
    _catalog = await _load_catalog(session)
    return _catalog


def get_catalog_source() -> str:
    return _catalog_source
