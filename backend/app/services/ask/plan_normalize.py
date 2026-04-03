# backend/app/services/ask/plan_normalize.py
from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple
import re

# نستعمل الموجود عندك أصلاً في plan_core
from backend.app.services.ask.plan_core import (
    _normalize_plan,
    _validate_plan,
    _infer_top_limit,
)

Plan = Dict[str, Any]


def _catalog_keys(catalog: dict, key: str) -> Set[str]:
    items = catalog.get(key) or []
    out: Set[str] = set()
    if isinstance(items, list):
        for it in items:
            if isinstance(it, str):
                out.add(it)
            elif isinstance(it, dict):
                k = it.get("key") or it.get("name")
                if isinstance(k, str) and k:
                    out.add(k)
    return out


def _dedupe_synonyms(plan: Plan, corrections: List[str]) -> Plan:
    plan = dict(plan or {})
    metrics = plan.get("metrics") or []
    dims = plan.get("dimensions") or []

    def _uniq(seq):
        out = []
        seen = set()
        for x in seq:
            if not isinstance(x, str):
                continue
            if x not in seen:
                out.append(x)
                seen.add(x)
        return out

    m0 = list(metrics)
    d0 = list(dims)

    metrics = _uniq(metrics)
    dims = _uniq(dims)

    # Canonical preferences
    if "discount_amount" in metrics and "discounts" in metrics:
        metrics = [m for m in metrics if m != "discounts"]
        corrections.append("dedupe:discounts_removed")
    if "order_quarter" in dims and "quarter" in dims:
        dims = [d for d in dims if d != "quarter"]
        corrections.append("dedupe:quarter_removed")
    if "order_year" in dims and "year" in dims:
        dims = [d for d in dims if d != "year"]
        corrections.append("dedupe:year_removed")

    if m0 != metrics:
        corrections.append("dedupe:metrics")
    if d0 != dims:
        corrections.append("dedupe:dimensions")

    plan["metrics"] = metrics
    plan["dimensions"] = dims
    return plan


def _autocorrect_plan(
    question: str,
    plan: Plan,
    catalog: dict,
    *,
    allowed_ops: Set[str],
    default_max_rows: int,
    max_rows_cap: int,
    corrections: List[str],
) -> Plan:
    plan = dict(plan or {})
    q_raw = (question or "").strip()
    q = q_raw.lower()

    metrics_ok = _catalog_keys(catalog, "metrics")
    dims_ok = _catalog_keys(catalog, "dimensions")

    dim_map = {
        "year": "order_year",
        "order_yr": "order_year",
        "yr": "order_year",
        "quarter": "order_quarter",
        "qtr": "order_quarter",
        "q": "order_quarter",
        "month": "month_start",
        "monthly": "month_start",
    }
    met_map = {
        "discounts": "discount_amount",
        "discount": "discount_amount",
        "gross": "gross_sales",
        "sales": "gross_sales",
        "qty": "order_quantity",
        "quantity": "order_quantity",
        "units": "order_quantity",
    }

    def _canon_dim(d: str) -> str:
        d0 = (d or "").strip()
        d1 = d0.lower()
        cand = dim_map.get(d1)
        if cand and cand in dims_ok:
            if cand != d0:
                corrections.append(f"dim_alias:{d0}->{cand}")
            return cand
        if d0 in dims_ok:
            return d0
        d2 = re.sub(r"[^a-z0-9_]+", "_", d1).strip("_")
        cand2 = dim_map.get(d2)
        if cand2 and cand2 in dims_ok:
            corrections.append(f"dim_alias:{d0}->{cand2}")
            return cand2
        if d2 in dims_ok:
            corrections.append(f"dim_norm:{d0}->{d2}")
            return d2
        return d0

    def _canon_met(m: str) -> str:
        m0 = (m or "").strip()
        m1 = m0.lower()
        cand = met_map.get(m1)
        if cand and cand in metrics_ok:
            if cand != m0:
                corrections.append(f"metric_alias:{m0}->{cand}")
            return cand
        if m0 in metrics_ok:
            return m0
        m2 = re.sub(r"[^a-z0-9_]+", "_", m1).strip("_")
        cand2 = met_map.get(m2)
        if cand2 and cand2 in metrics_ok:
            corrections.append(f"metric_alias:{m0}->{cand2}")
            return cand2
        if m2 in metrics_ok:
            corrections.append(f"metric_norm:{m0}->{m2}")
            return m2
        return m0

    # Normalize lists
    metrics = []
    for m in (plan.get("metrics") or []):
        if isinstance(m, str) and m.strip():
            metrics.append(_canon_met(m))

    dims = []
    for d in (plan.get("dimensions") or []):
        if isinstance(d, str) and d.strip():
            dims.append(_canon_dim(d))

    # Deduplicate preserve order
    def _uniq(seq):
        out = []
        seen = set()
        for x in seq:
            if x and x not in seen:
                out.append(x)
                seen.add(x)
        return out

    metrics = _uniq(metrics)
    dims = _uniq(dims)

    # Heuristic nudges for time dims
    if ("ربع" in q_raw or "quarter" in q) and "order_quarter" in dims_ok and "order_quarter" not in dims:
        dims.append("order_quarter")
        corrections.append("added:order_quarter")
    if ("سنة" in q_raw or "year" in q) and "order_year" in dims_ok and "order_year" not in dims:
        dims.append("order_year")
        corrections.append("added:order_year")

    # Prefer discount_amount over discounts
    if "discount_amount" in metrics_ok and "discount_amount" in metrics and "discounts" in metrics:
        metrics = [x for x in metrics if x != "discounts"]
        corrections.append("prefer:discount_amount")

    # Drop unknown keys
    before_m = list(metrics)
    before_d = list(dims)
    metrics = [m for m in metrics if m in metrics_ok]
    dims = [d for d in dims if d in dims_ok]
    if before_m != metrics:
        corrections.append("dropped_unknown_metrics")
    if before_d != dims:
        corrections.append("dropped_unknown_dimensions")

    plan["metrics"] = metrics
    plan["dimensions"] = dims

    # Filters
    norm_filters = []
    for f in (plan.get("filters") or []):
        if not isinstance(f, dict):
            continue
        f2 = dict(f)
        field = str(f2.get("field") or "").strip()
        op = str(f2.get("op") or "").strip().lower()
        if not field or op not in allowed_ops:
            continue

        # غالباً field dim
        field_c = _canon_dim(field)
        if field_c not in dims_ok and field_c not in metrics_ok:
            continue

        f2["field"] = field_c

        if op == "between":
            v = f2.get("value")
            if not isinstance(v, list) or len(v) != 2:
                continue

        norm_filters.append(f2)

    if len(norm_filters) != len(plan.get("filters") or []):
        corrections.append("filters_normalized")

    plan["filters"] = norm_filters

    # Sort
    norm_sort = []
    for s in (plan.get("sort") or []):
        if not isinstance(s, dict):
            continue
        s2 = dict(s)
        field = str(s2.get("field") or "").strip()
        if not field:
            continue

        field_c = _canon_met(field)
        if field_c not in metrics_ok and field_c not in dims_ok:
            field_c = _canon_dim(field)

        if field_c not in metrics_ok and field_c not in dims_ok:
            continue

        s2["field"] = field_c
        d = (s2.get("dir") or "desc").lower()
        s2["dir"] = "asc" if d == "asc" else "desc"
        norm_sort.append(s2)

    if not norm_sort and metrics:
        norm_sort = [{"field": metrics[0], "dir": "desc"}]
        corrections.append("sort_defaulted")

    plan["sort"] = norm_sort

    # Limit
    try:
        lim = int(plan.get("limit") or default_max_rows)
    except Exception:
        lim = default_max_rows
        corrections.append("limit_fixed_invalid")
    lim = max(1, min(max_rows_cap, lim))
    plan["limit"] = lim

    return plan


def _apply_heuristics(
    question: str,
    plan: Plan,
    catalog: dict,
    *,
    default_max_rows: int,
    corrections: List[str],
) -> Plan:
    plan = dict(plan or {})
    plan.setdefault("metrics", [])
    plan.setdefault("dimensions", [])
    plan.setdefault("filters", [])
    plan.setdefault("sort", [])
    plan.setdefault("limit", default_max_rows)

    q_raw = (question or "").strip()
    q = q_raw.lower()

    metrics_ok = _catalog_keys(catalog, "metrics")
    dims_ok = _catalog_keys(catalog, "dimensions")

    def add_dim(d: str) -> None:
        if d in dims_ok and d not in (plan.get("dimensions") or []):
            plan["dimensions"] = list(dict.fromkeys((plan.get("dimensions") or []) + [d]))
            corrections.append(f"add_dim:{d}")

    def add_metric(m: str) -> None:
        if m in metrics_ok and m not in (plan.get("metrics") or []):
            plan["metrics"] = list(dict.fromkeys((plan.get("metrics") or []) + [m]))
            corrections.append(f"add_metric:{m}")

    # Time grouping
    if any(x in q_raw for x in ["شهري", "شهريا", "بالشهر", "شهريًا"]) or "monthly" in q:
        add_dim("month_start")
        plan["limit"] = min(int(plan.get("limit") or default_max_rows), 60)

    quarter_hit = (
        any(x in q_raw for x in ["ربع", "بالربع", "ربع سنوي", "ربع سنوية", "ربعياً", "ربعيا"])
        or any(x in q for x in ["quarter", "qtr", "quarterly"])
    )
    if quarter_hit:
        add_dim("order_year")
        add_dim("order_quarter")

    # Metrics intent
    net_hit = any(x in q_raw for x in ["صافي", "صافية"]) or "net" in q
    gross_hit = "إجمالي" in q_raw and not net_hit
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

    # Compare: stable ordering
    compare_hit = ("قارن" in q_raw) or ("compare" in q)
    if compare_hit:
        ordered = []
        candidates = ["net_sales", "gross_sales", "gross_profit"]
        if discount_metric:
            candidates.insert(1, discount_metric)
        for k in candidates:
            if k in (plan.get("metrics") or []) and k not in ordered:
                ordered.append(k)
        for k in plan.get("metrics") or []:
            if k not in ordered:
                ordered.append(k)
        if ordered:
            plan["metrics"] = ordered

    # Top-N inference
    top_n = _infer_top_limit(question or "")
    if top_n is not None:
        plan["limit"] = min(5000, max(1, int(top_n)))
        corrections.append(f"topn:{plan['limit']}")

    return plan


def finalize_plan(
    question: str,
    plan: Plan,
    catalog: dict,
    *,
    default_max_rows: int,
    plan_autocorrect: bool,
    dedupe_synonyms: bool,
    allowed_ops: Set[str],
    max_rows_cap: int = 5000,
) -> Tuple[Plan, List[str]]:
    corrections: List[str] = []

    p = _normalize_plan(plan)

    if plan_autocorrect:
        p = _autocorrect_plan(
            question,
            p,
            catalog,
            allowed_ops=allowed_ops,
            default_max_rows=default_max_rows,
            max_rows_cap=max_rows_cap,
            corrections=corrections,
        )

    p = _apply_heuristics(
        question,
        p,
        catalog,
        default_max_rows=default_max_rows,
        corrections=corrections,
    )

    p = _normalize_plan(p)

    if dedupe_synonyms:
        p = _dedupe_synonyms(p, corrections)

    p = _validate_plan(p, catalog)

    return p, corrections
