from __future__ import annotations

import os
from typing import Any, Dict, Optional, Set

from fastapi import HTTPException
import re

# Extracted from services/ask/runner.py (Step3A)
# Goal: keep runner smaller with no behavior change.

# Allowed filter operators (canonical)
ALLOWED_OPS = {"=", "!=", ">", ">=", "<", "<=", "in", "between", "ilike"}


def _catalog_keys(catalog: dict, key: str) -> Set[str]:
    """Return allowed keys from catalog lists (supports list[str] or list[dict])."""
    items = catalog.get(key) or []
    out: Set[str] = set()
    if isinstance(items, list):
        for it in items:
            if isinstance(it, str):
                k = it.strip()
                if k:
                    out.add(k)
            elif isinstance(it, dict):
                k = it.get("key") or it.get("name") or it.get("metric_key") or it.get("dim_key") or ""
                if k:
                    out.add(str(k).strip())
    return out


DEFAULT_MAX_ROWS = int(os.getenv("DEFAULT_MAX_ROWS", "200"))
_ARABIC_DIGIT_MAP = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


def _normalize_plan(plan: Dict[str, Any]) -> Dict[str, Any]:
    plan = dict(plan or {})
    plan.setdefault("metrics", [])
    plan.setdefault("dimensions", [])
    plan.setdefault("filters", [])
    plan.setdefault("sort", [])
    plan.setdefault("limit", DEFAULT_MAX_ROWS)
    plan.setdefault("notes", "")

    # ensure list types
    for k in ("metrics", "dimensions", "filters", "sort"):
        v = plan.get(k)
        if v is None:
            plan[k] = []
        elif not isinstance(v, list):
            plan[k] = [v]

    # normalize filters
    norm_filters = []
    for f in plan.get("filters") or []:
        if not isinstance(f, dict):
            continue
        f = dict(f)
        if "op" not in f and "operator" in f:
            f["op"] = f.pop("operator")
        if f.get("op") in ("==", "==="):
            f["op"] = "="
        if isinstance(f.get("op"), str):
            f["op"] = f["op"].lower()
        norm_filters.append(f)
    plan["filters"] = norm_filters

    # normalize sort
    norm_sort = []
    for s in plan.get("sort") or []:
        if not isinstance(s, dict):
            continue
        s = dict(s)
        if "dir" not in s and "direction" in s:
            s["dir"] = s.pop("direction")
        d = (s.get("dir") or "desc").lower()
        s["dir"] = "asc" if d == "asc" else "desc"
        norm_sort.append(s)
    plan["sort"] = norm_sort

    # normalize limit
    try:
        plan["limit"] = int(plan.get("limit") or DEFAULT_MAX_ROWS)
    except Exception:
        plan["limit"] = DEFAULT_MAX_ROWS
    plan["limit"] = max(1, min(5000, plan["limit"]))

    return plan


def _validate_plan(plan: Dict[str, Any], catalog: dict) -> Dict[str, Any]:
    metrics_ok = _catalog_keys(catalog, "metrics")
    dims_ok = _catalog_keys(catalog, "dimensions")

    if not plan.get("metrics") and not plan.get("dimensions"):
        raise HTTPException(status_code=400, detail="Plan must include at least one metric or dimension.")

    for m in plan.get("metrics") or []:
        if m not in metrics_ok:
            raise HTTPException(status_code=400, detail=f"Unknown metric key: {m}")

    for d in plan.get("dimensions") or []:
        if d not in dims_ok:
            raise HTTPException(status_code=400, detail=f"Unknown dimension key: {d}")

    for f in plan.get("filters") or []:
        if not isinstance(f, dict):
            raise HTTPException(status_code=400, detail="Each filter must be an object")
        field = f.get("field")
        op = (f.get("op") or "").lower()
        if field not in dims_ok:
            raise HTTPException(status_code=400, detail=f"Unknown filter field: {field}")
        if op not in ALLOWED_OPS:
            raise HTTPException(status_code=400, detail=f"Unsupported operator: {op}")

    if plan.get("sort"):
        s = plan["sort"][0]
        field = s.get("field")
        if field and (field not in metrics_ok) and (field not in dims_ok):
            raise HTTPException(status_code=400, detail=f"Unknown sort field: {field}")

    return plan


# -----------------------------------------------------------------------------
# Heuristics + rule-based fallback
# -----------------------------------------------------------------------------
# --- Top-N parsing helpers (v3) ------------------------------------------------
_ARABIC_DIGIT_MAP = str.maketrans(
    {
        "٠": ord("0"),
        "١": ord("1"),
        "٢": ord("2"),
        "٣": ord("3"),
        "٤": ord("4"),
        "٥": ord("5"),
        "٦": ord("6"),
        "٧": ord("7"),
        "٨": ord("8"),
        "٩": ord("9"),
        "۰": ord("0"),
        "۱": ord("1"),
        "۲": ord("2"),
        "۳": ord("3"),
        "۴": ord("4"),
        "۵": ord("5"),
        "۶": ord("6"),
        "۷": ord("7"),
        "۸": ord("8"),
        "۹": ord("9"),
    }
)

_ARABIC_NUMBER_WORDS = {
    "واحد": 1,
    "واحدة": 1,
    "اثنين": 2,
    "اثنان": 2,
    "اثنتين": 2,
    "اثنتان": 2,
    "ثلاث": 3,
    "ثلاثة": 3,
    "أربع": 4,
    "اربعة": 4,
    "أربعة": 4,
    "خمس": 5,
    "خمسة": 5,
    "ست": 6,
    "ستة": 6,
    "سبع": 7,
    "سبعة": 7,
    "ثمان": 8,
    "ثمانية": 8,
    "تسع": 9,
    "تسعة": 9,
    "عشر": 10,
    "عشرة": 10,
    "عشرين": 20,
    "ثلاثين": 30,
    "أربعين": 40,
    "خمسين": 50,
    "مئة": 100,
    "مائة": 100,
}

_TOP_HINTS = ("top", "highest", "best", "أعلى", "اعلى", "الأعلى", "الاعلى", "أفضل", "الافضل", "الأفضل")
_RANKING_OBJECTS = (
    "مدن",
    "المدن",
    "مدينة",
    "cities",
    "city",
    "عملاء",
    "العملاء",
    "customers",
    "customer",
    "منتجات",
    "المنتجات",
    "products",
    "product",
    "اصناف",
    "الأصناف",
    "items",
    "item",
)


def _infer_top_limit(question: str) -> Optional[int]:
    """Infer intended Top-N from text. Returns None if not a ranking query."""
    q = (question or "").strip()
    if not q:
        return None

    q_norm = q.translate(_ARABIC_DIGIT_MAP)
    ql = q_norm.lower()

    # explicit digits anywhere near top hints
    if any(h in q for h in _TOP_HINTS) or any(h in ql for h in ("top", "highest", "best")):
        m = re.search(r"\b(?:top\s*)?(\d{1,4})\b", ql)
        if m:
            try:
                n = int(m.group(1))
                return n
            except Exception:
                pass

        # Arabic word numbers after hints: "أعلى عشرة"
        for w, n in _ARABIC_NUMBER_WORDS.items():
            if w in q:
                return n

        # default to 10 ONLY if it looks like a ranking over entities (cities/products/etc.)
        if any(obj in q for obj in _RANKING_OBJECTS) or any(obj in ql for obj in _RANKING_OBJECTS):
            return 10

    return None


def _apply_heuristics(question: str, plan: Dict[str, Any], catalog: Optional[dict] = None) -> Dict[str, Any]:
    """Post-process a plan (from LLM or rule-based) using lightweight heuristics.

    Goals:
    - Add month/quarter/year grouping when mentioned.
    - Add discount metric when asked.
    - Infer Top-N limit for ranking queries.
    - Keep SAFE: only add keys that exist in the catalog.
    """
    catalog = catalog or {}

    q_raw = (question or "").strip()
    q = q_raw.lower()

    plan = dict(plan or {})
    plan.setdefault("metrics", [])
    plan.setdefault("dimensions", [])
    plan.setdefault("filters", [])
    plan.setdefault("sort", [])
    plan.setdefault("limit", DEFAULT_MAX_ROWS)

    metrics_ok = _catalog_keys(catalog, "metrics")
    dims_ok = _catalog_keys(catalog, "dimensions")

    def add_dim(d: str) -> None:
        if d in dims_ok and d not in (plan.get("dimensions") or []):
            plan["dimensions"] = list(dict.fromkeys((plan.get("dimensions") or []) + [d]))

    def add_metric(m: str) -> None:
        if m in metrics_ok and m not in (plan.get("metrics") or []):
            plan["metrics"] = list(dict.fromkeys((plan.get("metrics") or []) + [m]))

    # -----------------------
    # Time grouping heuristics
    # -----------------------
    if any(x in q_raw for x in ["شهري", "شهريا", "بالشهر", "شهريًا"]) or "monthly" in q:
        add_dim("month_start")
        plan["limit"] = min(int(plan.get("limit") or DEFAULT_MAX_ROWS), 60)

    quarter_hit = (
        any(x in q_raw for x in ["ربع", "بالربع", "ربع سنوي", "ربع سنوية", "ربعياً", "ربعيا"])
        or any(x in q for x in ["quarter", "qtr", "quarterly"])
    )
    if quarter_hit:
        add_dim("order_year")
        add_dim("order_quarter")

    yearly_hit = (
        any(x in q_raw for x in ["سنة", "سنوي", "سنوياً", "سنويا", "بالسنة", "حسب السنة"])
        or any(x in q for x in ["year", "annual", "yearly"])
    )
    if yearly_hit:
        add_dim("order_year")

    # -----------------------
    # Metric intent heuristics
    # -----------------------
    net_hit = any(x in q_raw for x in ["صافي", "صافية"]) or "net" in q
    gross_hit = ("إجمالي" in q_raw) and (not net_hit)
    disc_hit = any(x in q_raw for x in ["خصم", "خصومات"]) or any(x in q for x in ["discount", "discounts"])

    discount_metric = None
    for cand in ["discount_amount", "discounts", "discount"]:
        if cand in metrics_ok:
            discount_metric = cand
            break

    if net_hit:
        add_metric("net_sales")
        if "net_sales" in metrics_ok:
            plan["sort"] = [{"field": "net_sales", "dir": "desc"}]

    if gross_hit:
        add_metric("gross_sales")
        if not plan.get("sort") and "gross_sales" in metrics_ok:
            plan["sort"] = [{"field": "gross_sales", "dir": "desc"}]

    if disc_hit and discount_metric:
        add_metric(discount_metric)

    compare_hit = ("قارن" in q_raw) or ("compare" in q)
    if compare_hit:
        ordered = []
        candidates = ["net_sales", "gross_sales", "gross_profit"]
        if discount_metric:
            candidates.insert(1, discount_metric)
        for k in candidates:
            if k and k in (plan.get("metrics") or []) and k not in ordered:
                ordered.append(k)
        for k in plan.get("metrics") or []:
            if k not in ordered:
                ordered.append(k)
        plan["metrics"] = ordered or (plan.get("metrics") or [])

    # -----------------------
    # City mapping heuristics
    # -----------------------
    city_map = {
        "سيدني": "Sydney",
        "سيدنى": "Sydney",
        "sydney": "Sydney",
        "ملبورن": "Melbourne",
        "ميلبورن": "Melbourne",
        "melbourne": "Melbourne",
    }
    city_val = None
    for k, v in city_map.items():
        if k in q:
            city_val = v
            break

    if city_val and "city" in dims_ok:
        filters = plan.get("filters") or []
        if not any(isinstance(f, dict) and f.get("field") == "city" for f in filters):
            filters.append({"field": "city", "op": "=", "value": city_val})
        plan["filters"] = filters
        add_dim("city")

    # -----------------------
    # Top-N inference
    # -----------------------
    top_n = _infer_top_limit(question or "")
    if top_n is not None:
        plan["limit"] = min(5000, max(1, int(top_n)))

    return plan


def _rule_based_plan(question: str, catalog: dict) -> Dict[str, Any]:
    """Very simple fallback that works offline."""
    q = (question or "").strip()
    ql = q.lower()

    dims_ok = _catalog_keys(catalog, "dimensions")
    metrics_ok = _catalog_keys(catalog, "metrics")

    plan: Dict[str, Any] = {
        "metrics": [],
        "dimensions": [],
        "filters": [],
        "sort": [],
        "limit": DEFAULT_MAX_ROWS,
        "notes": "rule_based",
    }

    # -----------------------------------------------------------------
    # NEW: order_count (عدد الطلبات) — أعلى أولوية لو كان السؤال واضح
    # -----------------------------------------------------------------
    count_hit = any(x in q for x in ["عدد", "كم", "العدد"]) or any(x in ql for x in ["count", "how many", "number of"])
    order_hit = any(x in q for x in ["طلب", "طلبات", "الطلبات"]) or any(x in ql for x in ["order", "orders"])

    order_count_selected = False
    if (("عدد الطلبات" in q) or (count_hit and order_hit)) and "order_count" in metrics_ok:
        plan["metrics"] = ["order_count"]
        plan["sort"] = [{"field": "order_count", "dir": "desc"}]
        order_count_selected = True

    # pick metric (existing logic) — only if not order_count
    if not order_count_selected:
        if ("صافي" in q or "صافية" in q or "net" in ql) and "net_sales" in metrics_ok:
            plan["metrics"] = ["net_sales"]
            plan["sort"] = [{"field": "net_sales", "dir": "desc"}]
        elif "إجمالي" in q and "gross_sales" in metrics_ok:
            plan["metrics"] = ["gross_sales"]
            plan["sort"] = [{"field": "gross_sales", "dir": "desc"}]
        elif "gross_profit" in metrics_ok and "ربح" in q:
            plan["metrics"] = ["gross_profit"]
            plan["sort"] = [{"field": "gross_profit", "dir": "desc"}]
        else:
            # safe default
            default_metric = "net_sales" if "net_sales" in metrics_ok else next(iter(metrics_ok), "")
            if default_metric:
                plan["metrics"] = [default_metric]
                plan["sort"] = [{"field": default_metric, "dir": "desc"}]

        # discounts / compare (Phase 3 v4) — keep existing behavior
        disc_hit = any(x in q for x in ["خصم", "خصومات"]) or any(x in ql for x in ["discount", "discounts"])
        discount_metric = None
        for cand in ["discount_amount", "discounts", "discount"]:
            if cand in metrics_ok:
                discount_metric = cand
                break

        compare_hit = ("قارن" in q) or ("compare" in ql)

        if disc_hit and discount_metric:
            if compare_hit and "net_sales" in (plan.get("metrics") or []):
                plan["metrics"] = list(dict.fromkeys((plan.get("metrics") or []) + [discount_metric]))
                # keep sorting by net_sales
                plan["sort"] = [{"field": "net_sales", "dir": "desc"}] if "net_sales" in metrics_ok else (plan.get("sort") or [])
            else:
                plan["metrics"] = [discount_metric]
                plan["sort"] = [{"field": discount_metric, "dir": "desc"}]

    # monthly
    if any(x in q for x in ["شهري", "شهريا", "بالشهر", "شهريًا"]) and "month_start" in dims_ok:
        plan["dimensions"].append("month_start")

    # quarterly
    if any(x in q for x in ["ربع", "بالربع", "ربع سنوي", "ربع سنوية", "ربعياً", "ربعيا"]) or any(
        x in ql for x in ["quarter", "qtr", "quarterly"]
    ):
        if "order_year" in dims_ok:
            plan["dimensions"].append("order_year")
        if "order_quarter" in dims_ok:
            plan["dimensions"].append("order_quarter")

    # yearly
    if any(x in q for x in ["سنة", "سنوي", "سنوياً", "سنويا", "بالسنة", "حسب السنة"]) or any(
        x in ql for x in ["year", "annual", "yearly"]
    ):
        if "order_year" in dims_ok:
            plan["dimensions"].append("order_year")

    # basic "by" logic (city / cities / مدن)
    if (any(x in q for x in ["مدينة", "مدن", "المدن"]) or any(x in ql for x in ["city", "cities"])) and "city" in dims_ok:
        plan["dimensions"].append("city")

    # products / categories (rule-based dimension selection)
    cat_hit = any(x in q for x in ["فئة المنتج", "تصنيف المنتج", "قسم المنتج"]) or any(
        x in ql for x in ["product category", "category", "segment"]
    )
    if cat_hit and "product_category" in dims_ok:
        plan["dimensions"].append("product_category")
    else:
        prod_hit = any(
            x in q for x in ["منتج", "منتجات", "المنتجات", "صنف", "أصناف", "اصناف", "الأصناف", "سلعة", "سلع"]
        ) or any(x in ql for x in ["product", "products", "product name", "item", "items", "sku"])
        if prod_hit and "product_name" in dims_ok:
            plan["dimensions"].append("product_name")

    cont_hit = any(x in q for x in ["عبوة", "تغليف", "حاوية", "نوع العبوة", "نوع التغليف"]) or any(
        x in ql for x in ["container", "packaging", "pack"]
    )
    if cont_hit and "product_container" in dims_ok:
        plan["dimensions"].append("product_container")

    # city mapping
    city_map = {
        "سيدني": "Sydney",
        "sydney": "Sydney",
        "ملبورن": "Melbourne",
        "melbourne": "Melbourne",
    }
    if "city" in dims_ok:
        for k, v in city_map.items():
            if k in ql:
                plan["filters"].append({"field": "city", "op": "=", "value": v})
                if "city" not in plan["dimensions"]:
                    plan["dimensions"].append("city")
                break

    # state / province (dimension selection)
    if (any(x in q for x in ["ولاية", "الولاية", "محافظة", "المحافظة"]) or any(x in ql for x in ["state", "states", "province"])) and "state" in dims_ok:
        plan["dimensions"].append("state")

    # Top-N
    top_n = _infer_top_limit(question)
    if top_n is not None:
        plan["limit"] = min(5000, max(1, int(top_n)))

    # dedupe dimensions
    plan["dimensions"] = list(dict.fromkeys(plan["dimensions"]))
    return plan



# -----------------------------------------------------------------------------
# Cache (bi_meta.plan_cache)
# -----------------------------------------------------------------------------
