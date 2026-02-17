from __future__ import annotations

# Extracted from services/ask/runner.py
# Goal: keep runner.py smaller with no behavior change.

def _augment_catalog(catalog: dict) -> dict:
    """Augment catalog with known safe keys that exist in bi.vw_fact_sales_line_clean.

    Enables quarter/year grouping and key metrics even if the DB catalog is missing them.
    """
    if not isinstance(catalog, dict):
        return catalog

    def _ensure_key(group: str, key: str, default_obj: dict | None = None) -> None:
        arr = catalog.get(group)
        if arr is None:
            catalog[group] = [key]
            return
        if not isinstance(arr, list):
            return

        # list[dict]
        if arr and isinstance(arr[0], dict):
            keys = {(x.get("key") or x.get("name") or "").strip() for x in arr if isinstance(x, dict)}
            if key not in keys:
                catalog[group].append(default_obj or {"key": key, "label": key})
        else:
            # list[str]
            keys = {str(x).strip() for x in arr}
            if key not in keys:
                catalog[group].append(key)

    # Dimensions
    for dim_key in ["order_year", "order_quarter"]:
        _ensure_key("dimensions", dim_key, {"key": dim_key, "label": dim_key})

    # Metrics
    _ensure_key("metrics", "discount_amount", {"key": "discount_amount", "label": "discount_amount"})
    _ensure_key("metrics", "order_count", {"key": "order_count", "label": "order_count"})

    return catalog
