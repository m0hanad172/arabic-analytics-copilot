"""
Arabic Analytics Copilot - /ask endpoint (stable + cache + optional Gemini)

Drop this file into: backend/app/api/routes/ask.py

Goals:
- Never crash when Gemini quota is exceeded (fallback to cache or rule-based).
- Works with BOTH catalog shapes:
    A) {"metrics":[{"key":"net_sales",...}], "dimensions":[{"key":"city",...}]}
    B) {"metrics":["net_sales",...], "dimensions":["city",...]}
- Cache first (bi_meta.plan_cache), then (optional) LLM, then rule-based fallback.
"""

from __future__ import annotations

import os
import re
import json
import time
import hashlib
from typing import Any, Optional, List, Dict, Set
from pathlib import Path

import asyncpg
from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException, Query

# SQL guardrails (security)
from backend.app.core.sql_guardrails import guard_sql_or_raise
from pydantic import BaseModel, Field


# Optional Gemini
from .catalog import _augment_catalog
from .plan_core import _normalize_plan, _validate_plan, _rule_based_plan, _infer_top_limit
from .plan_core import _ARABIC_DIGIT_MAP
try:
    from google import genai  # type: ignore
except Exception:  # pragma: no cover
    genai = None


from .cache import _normalize_question, _cache_get_plan, _cache_upsert_plan

try:
    from .plan_core import ALLOWED_OPS as _ALLOWED_OPS
except Exception:
    _ALLOWED_OPS = {"=", "!=", ">", ">=", "<", "<=", "in", "between", "ilike"}

ALLOWED_OPS = _ALLOWED_OPS

from backend.app.services.ask.plan_normalize import finalize_plan



ASK_VERSION = "v4.7"
# -----------------------------------------------------------------------------
# ENV
# -----------------------------------------------------------------------------
# This file should live at: backend/app/api/routes/ask.py
# parents[3] -> backend/
ENV_PATH = Path(__file__).resolve().parents[3] / ".env"
load_dotenv(ENV_PATH)

DATABASE_URL = os.getenv("DATABASE_URL", "")
STATEMENT_TIMEOUT_MS = int(os.getenv("STATEMENT_TIMEOUT_MS", "8000"))
DEFAULT_MAX_ROWS = int(os.getenv("DEFAULT_MAX_ROWS", "200"))
DEDUPE_SYNONYMS = os.getenv("DEDUPE_SYNONYMS", "0") in ("1", "true", "True", "yes", "YES")
PLAN_AUTOCORRECT = os.getenv("PLAN_AUTOCORRECT", "1") in ("1", "true", "True", "yes", "YES")

GEMINI_API_KEY = (os.getenv("GEMINI_API_KEY") or "").strip()
GEMINI_MODEL = (os.getenv("GEMINI_MODEL", "gemini-3-flash") or "").strip()

LLM_ENABLED = bool(GEMINI_API_KEY) and genai is not None

gclient = None


KW_MAP: Dict[str, List[str]] = {
    # metrics
    "net_sales": ["صافي", "صافيه", "net", "net sales", "صافي المبيعات"],
    "gross_sales": ["اجمالي", "إجمالي", "مبيعات", "gross", "sales", "gross sales", "اجمالي المبيعات"],
    "discount_amount": ["خصم", "خصومات", "discount", "discounts", "قيمة الخصم"],
    "discounts": ["خصم", "خصومات", "discount", "discounts"],
    "gross_profit": ["ربح", "gross profit", "profit"],
    "profit_after_shipping": ["بعد الشحن", "profit after shipping"],
    "shipping_cost": ["شحن", "shipping", "shipping cost"],
    "ship_delay_days": ["تأخير", "delay", "late"],
    "order_quantity": ["كمية", "وحدات", "quantity", "units"],

    # dimensions
    "city": ["مدينة", "مدن", "city"],
    "state": ["ولاية", "state"],
    "order_year": ["سنة", "سنوي", "year"],
    "order_quarter": ["ربع", "ربع سنوي", "quarter", "qtr", "q1", "q2", "q3", "q4"],
    "month_start": ["شهر", "شهري", "monthly", "month"],
    "order_month": ["شهر", "شهري", "monthly", "month"],
    "product_category": ["فئة", "تصنيف", "category"],
    "product_name": ["منتج", "منتجات", "product"],
    "customer_type": ["عميل", "زبون", "customer"],
    "account_manager": ["مدير", "manager", "account manager"],
    "ship_mode": ["طريقة الشحن", "shipping mode", "ship mode"],
}



def _get_gclient():
    """
    Lazy-init Gemini client with compatibility:
      - New SDK: `from google import genai`  -> genai.Client(...)
      - Legacy SDK: `import google.generativeai as genai` -> genai.GenerativeModel(...)
    Returns a client that supports: gclient.models.generate_content(model=..., contents=...)
    """
    global gclient
    if gclient is not None:
        return gclient

    # Defensive checks (runner.py already has these globals عادة)
    api_key = (globals().get("GEMINI_API_KEY") or "").strip()
    if not api_key:
        gclient = None
        return None

    model_name = (
        globals().get("GEMINI_MODEL")
        or globals().get("MODEL_NAME")
        or "gemini-1.5-flash"
    )

    # --- Try NEW SDK (google-genai) ---
    try:
        from google import genai as genai_new  # type: ignore
        if hasattr(genai_new, "Client"):
            gclient = genai_new.Client(api_key=api_key)
            return gclient
    except Exception:
        pass

    # --- Try LEGACY SDK (google-generativeai) ---
    try:
        import google.generativeai as genai_legacy  # type: ignore

        # configure once
        try:
            genai_legacy.configure(api_key=api_key)
        except Exception:
            pass

        model = genai_legacy.GenerativeModel(model_name)

        class _CompatModels:
            def __init__(self, m):
                self._m = m

            def generate_content(self, *args, **kwargs):
                # new SDK uses: generate_content(model=..., contents=...)
                contents = kwargs.get("contents")
                if contents is None:
                    # fallback positional
                    if len(args) >= 2:
                        contents = args[1]
                    elif len(args) == 1:
                        contents = args[0]
                    else:
                        contents = ""

                return self._m.generate_content(contents)

        class _CompatClient:
            def __init__(self, m):
                self.models = _CompatModels(m)

        gclient = _CompatClient(model)
        return gclient
    except Exception:
        gclient = None
        return None


def _asyncpg_dsn(sqlalchemy_url: str) -> str:
    # DATABASE_URL is usually: postgresql+asyncpg://...
    return sqlalchemy_url.replace("postgresql+asyncpg://", "postgresql://", 1)


def _ensure_json_obj(x: Any) -> Any:
    """asyncpg may return dict already for json/jsonb; if it returns a string, parse it."""
    if isinstance(x, str):
        try:
            return json.loads(x)
        except Exception:
            return x
    return x


async def _db_fetchval(sql: str, *args) -> Any:
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set in backend/.env")
    dsn = _asyncpg_dsn(DATABASE_URL)
    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute(f"SET statement_timeout = {STATEMENT_TIMEOUT_MS};")
        val = await conn.fetchval(sql, *args)
        return _ensure_json_obj(val)
    finally:
        await conn.close()


async def _db_fetchrow(sql: str, *args) -> Optional[dict]:
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set in backend/.env")
    dsn = _asyncpg_dsn(DATABASE_URL)
    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute(f"SET statement_timeout = {STATEMENT_TIMEOUT_MS};")
        row = await conn.fetchrow(sql, *args)
        return dict(row) if row else None
    finally:
        await conn.close()


async def _db_fetch(sql: str, *args) -> list[dict]:
    """Run a SELECT and return rows as list of dicts."""
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set in backend/.env")
    dsn = _asyncpg_dsn(DATABASE_URL)
    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute(f"SET statement_timeout = {STATEMENT_TIMEOUT_MS};")
        recs = await conn.fetch(sql, *args)
        return [dict(r) for r in recs]
    finally:
        await conn.close()


# -----------------------------------------------------------------------------
# Catalog
# -----------------------------------------------------------------------------
def _catalog_keys(catalog: dict, key: str) -> Set[str]:
    """
    Support both:
      - catalog["metrics"] as list[str]
      - catalog["metrics"] as list[{"key": "...", ...}]
    """
    items = catalog.get(key) or []
    out: Set[str] = set()

    if isinstance(items, list):
        for it in items:
            if isinstance(it, str):
                out.add(it)
            elif isinstance(it, dict):
                # prefer "key", fallback to "name"
                k = it.get("key") or it.get("name")
                if isinstance(k, str) and k:
                    out.add(k)
    return out




async def _get_catalog() -> dict:
    """
    Try:
      1) SELECT bi_meta.get_catalog();
      2) SELECT bi_meta.get_catalog($1)::jsonb;   (if you later add a schema arg)
    """
    try:
        catalog = await _db_fetchval("SELECT bi_meta.get_catalog();")
    except Exception:
        # fallback signature with one argument (optional)
        catalog = await _db_fetchval("SELECT bi_meta.get_catalog($1)::jsonb;", "bi")

    if not catalog:
        raise HTTPException(status_code=500, detail="Catalog is empty. Did you create bi_meta.get_catalog()?")
    if not isinstance(catalog, dict):
        raise HTTPException(status_code=500, detail="Catalog returned non-JSON object.")
    catalog = _augment_catalog(catalog)

    return catalog


# -----------------------------------------------------------------------------
# Plan parsing + validation
# -----------------------------------------------------------------------------
def _extract_json(text: str) -> Dict[str, Any]:
    """Gemini may wrap JSON in text/code fences; grab the first JSON object."""
    if not text:
        raise ValueError("Empty LLM response")

    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\s*```$", "", t)

    # direct parse
    try:
        obj = json.loads(t)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass

    # regex slice
    m = re.search(r"\{.*\}", t, flags=re.DOTALL)
    if not m:
        raise ValueError("No JSON object found in LLM output")
    obj = json.loads(m.group(0))
    if not isinstance(obj, dict):
        raise ValueError("JSON is not an object")
    return obj
# -----------------------------------------------------------------------------
# Lightweight "RAG" catalog scoping for LLM (quality + lower token use)
# -----------------------------------------------------------------------------
SCOPE_TOPK_METRICS = int(os.getenv("SCOPE_TOPK_METRICS", "25"))
SCOPE_TOPK_DIMS = int(os.getenv("SCOPE_TOPK_DIMS", "25"))


def _item_key(it: Any) -> str:
    if isinstance(it, dict):
        return str(it.get("key") or it.get("name") or it.get("metric_key") or it.get("dim_key") or "").strip()
    return str(it).strip()


def _slim_item(it: Any) -> Any:
    """Keep only light fields to reduce prompt tokens."""
    if isinstance(it, dict):
        k = _item_key(it)
        if not k:
            return it
        label = it.get("label") or it.get("display_name_ar") or it.get("display_name_en") or k
        return {"key": k, "label": str(label)}
    return _item_key(it)


_AR_DIACRITICS = re.compile(r"[\u0617-\u061A\u064B-\u0652\u0670]")
_NON_WORD = re.compile(r"[^\w\u0600-\u06FF]+")

def _norm_ar(text: str) -> str:
    if not text:
        return ""
    t = text.strip()
    t = _AR_DIACRITICS.sub("", t)
    t = (t.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
           .replace("ى", "ي").replace("ة", "ه"))
    t = t.lower()
    t = _NON_WORD.sub(" ", t)
    return re.sub(r"\s+", " ", t).strip()

def _tokens(text: str) -> set[str]:
    t = _norm_ar(text)
    return {x for x in t.split(" ") if len(x) >= 2}

def _item_label(it: Any) -> str:
    if isinstance(it, dict):
        return str(
            it.get("label")
            or it.get("display_name_ar")
            or it.get("display_name_en")
            or it.get("name")
            or it.get("key")
            or ""
        )
    return str(it or "")



def _score_item(question: str, it: Any, kind: str) -> int:
    q_raw = (question or "").strip()
    q_norm = _norm_ar(q_raw)
    q_toks = _tokens(q_raw)

    key = _item_key(it)
    label = _item_label(it)

    key_norm = _norm_ar(key)
    label_norm = _norm_ar(label)

    score = 0

    # 1) ذكر مباشر للـ key/label
    if key_norm and key_norm in q_norm:
        score += 8
    if label_norm and label_norm in q_norm and label_norm != key_norm:
        score += 6

    # 2) hits من الكلمات المفتاحية (synonyms)
    for kw in KW_MAP.get(key, []):
        kw_norm = _norm_ar(str(kw))
        if kw_norm and kw_norm in q_norm:
            score += 5

    # 3) overlap tokens (إشارة ضعيفة)
    overlap = len(q_toks & (_tokens(key) | _tokens(label)))
    score += min(4, overlap)

    # 4) Bias حسب نوع السؤال
    # إذا السؤال فيه "حسب" نعطي dimensions boost
    if kind == "dimension" and ("حسب" in q_raw or "by" in q_norm):
        score += 2

    # إذا السؤال فيه compare/اجمالي/مجموع نعطي metrics boost
    if kind == "metric" and (("compare" in q_norm) or any(x in q_raw for x in ["قارن", "اجمالي", "إجمالي", "مجموع"])):
        score += 2

    # إذا السؤال فيه "اعلى/Top" نعطي dimensions boost لأنها غالباً grouping key
    if kind == "dimension" and any(x in q_raw for x in ["اعلى", "أعلى", "top", "الأعلى"]):
        score += 1

    return score


def _scope_catalog_for_llm(question: str, catalog: dict) -> dict:
    """Return a filtered/slim catalog for LLM prompt to improve quality."""
    if not isinstance(catalog, dict):
        return catalog

    metrics = catalog.get("metrics") or []
    dims = catalog.get("dimensions") or []

    m_scored = []
    for it in metrics if isinstance(metrics, list) else []:
        k = _item_key(it)
        if not k:
            continue
        m_scored.append((_score_item(question, it, "metric"), k, it))

    d_scored = []
    for it in dims if isinstance(dims, list) else []:
        k = _item_key(it)
        if not k:
            continue
        d_scored.append((_score_item(question, it, "dimension"), k, it))

    # keep top-scoring items; if score==0 keep none initially
    m_scored.sort(key=lambda x: (-x[0], x[1]))
    d_scored.sort(key=lambda x: (-x[0], x[1]))

    m_keep = [it for sc, k, it in m_scored if sc > 0][:SCOPE_TOPK_METRICS]
    d_keep = [it for sc, k, it in d_scored if sc > 0][:SCOPE_TOPK_DIMS]

    # sensible defaults if too empty
    m_keys = {_item_key(x) for x in m_keep}
    d_keys = {_item_key(x) for x in d_keep}

    def _add_default(group_list: list, group_all: list, wanted_keys: List[str]) -> None:
        existing = {_item_key(x) for x in group_list}
        for wk in wanted_keys:
            if wk in existing:
                continue
            for it in group_all:
                if _item_key(it) == wk:
                    group_list.append(it)
                    existing.add(wk)
                    break

    # defaults for common analytics
    _add_default(m_keep, metrics if isinstance(metrics, list) else [], ["net_sales", "gross_sales", "discount_amount", "discounts"])
    _add_default(d_keep, dims if isinstance(dims, list) else [], ["city", "order_year", "order_quarter", "month_start"])

    # slim down to reduce prompt tokens
    return {
        "allowed_schema": catalog.get("allowed_schema") or "bi",
        "metrics": [_slim_item(x) for x in m_keep],
        "dimensions": [_slim_item(x) for x in d_keep],
    }





def _dedupe_synonyms(plan: Dict[str, Any]) -> Dict[str, Any]:
    """Optional cleanup to avoid duplicate synonymous keys (LLM sometimes outputs both)."""
    plan = dict(plan or {})
    metrics = plan.get("metrics") or []
    dims = plan.get("dimensions") or []

    # preserve order, unique
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

    metrics = _uniq(metrics)
    dims = _uniq(dims)

    # Canonical preferences
    if "discount_amount" in metrics and "discounts" in metrics:
        metrics = [m for m in metrics if m != "discounts"]
    if "order_quarter" in dims and "quarter" in dims:
        dims = [d for d in dims if d != "quarter"]
    if "order_year" in dims and "year" in dims:
        dims = [d for d in dims if d != "year"]

    plan["metrics"] = metrics
    plan["dimensions"] = dims
    return plan



def _autocorrect_plan(question: str, plan: Dict[str, Any], catalog: dict) -> Dict[str, Any]:
    """
    Autocorrect LLM plans (and even rule-based) to reduce 400/500 errors:
    - Map common synonyms to canonical keys that exist in the catalog.
    - Drop unknown metrics/dimensions/filters/sort fields (best-effort).
    - Remove duplicates and enforce sane limit.
    This runs BEFORE _validate_plan().
    """
    plan = dict(plan or {})
    q_raw = (question or "").strip()
    q = q_raw.lower()

    metrics_ok = _catalog_keys(catalog, "metrics")
    dims_ok = _catalog_keys(catalog, "dimensions")

    # Canonical mapping (only applied if target exists in catalog)
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
            return cand
        # If already valid
        if d0 in dims_ok:
            return d0
        # Some LLMs output "orderQuarter"/"order_quarter" variations
        d2 = re.sub(r"[^a-z0-9_]+", "_", d1).strip("_")
        cand2 = dim_map.get(d2)
        if cand2 and cand2 in dims_ok:
            return cand2
        if d2 in dims_ok:
            return d2
        return d0  # may be dropped later

    def _canon_met(m: str) -> str:
        m0 = (m or "").strip()
        m1 = m0.lower()
        cand = met_map.get(m1)
        if cand and cand in metrics_ok:
            return cand
        if m0 in metrics_ok:
            return m0
        m2 = re.sub(r"[^a-z0-9_]+", "_", m1).strip("_")
        cand2 = met_map.get(m2)
        if cand2 and cand2 in metrics_ok:
            return cand2
        if m2 in metrics_ok:
            return m2
        return m0  # may be dropped later

    # Normalize lists + map synonyms
    metrics = []
    for m in (plan.get("metrics") or []):
        if isinstance(m, str) and m.strip():
            metrics.append(_canon_met(m))

    dims = []
    for d in (plan.get("dimensions") or []):
        if isinstance(d, str) and d.strip():
            dims.append(_canon_dim(d))

    # Remove duplicates while preserving order
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

    # Heuristic nudges (only if keys exist)
    if ("ربع" in q_raw or "quarter" in q) and "order_quarter" in dims_ok and "order_quarter" not in dims:
        dims.append("order_quarter")
    if ("سنة" in q_raw or "year" in q) and "order_year" in dims_ok and "order_year" not in dims:
        dims.append("order_year")

    # Prefer discount_amount over discounts if both exist
    if "discount_amount" in metrics_ok and "discount_amount" in metrics and "discounts" in metrics:
        metrics = [x for x in metrics if x != "discounts"]

    # Drop unknown keys (best effort)
    metrics = [m for m in metrics if m in metrics_ok]
    dims = [d for d in dims if d in dims_ok]

    plan["metrics"] = metrics
    plan["dimensions"] = dims

    # Filters: map field + drop unknown
    norm_filters = []
    for f in (plan.get("filters") or []):
        if not isinstance(f, dict):
            continue
        f2 = dict(f)
        field = str(f2.get("field") or "").strip()
        op = str(f2.get("op") or "").strip().lower()
        if not field or op not in ALLOWED_OPS:
            continue

        field_c = _canon_dim(field) if field not in metrics_ok else _canon_met(field)
        # Filters are usually dims; allow filtering by metric only if present in metrics_ok
        if field_c in dims_ok or field_c in metrics_ok:
            f2["field"] = field_c
        else:
            continue

        # Basic value sanity for between
        if op == "between":
            v = f2.get("value")
            if not isinstance(v, list) or len(v) != 2:
                continue
        norm_filters.append(f2)
    plan["filters"] = norm_filters

    # Sort: map field + drop unknown; if empty and metrics exist, default to first metric desc
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
    plan["sort"] = norm_sort

    # Limit sanity
    MAX_ROWS_CAP = int(os.getenv("MAX_ROWS_CAP", "5000"))
    try:
        plan["limit"] = int(plan.get("limit") or DEFAULT_MAX_ROWS)
    except Exception:
        plan["limit"] = DEFAULT_MAX_ROWS
    plan["limit"] = max(1, min(MAX_ROWS_CAP, plan["limit"]))

    return plan
# Hints used by _infer_top_limit() to detect ranking/top-N questions (Arabic + common variants)


def _apply_heuristics(question: str, plan: Dict[str, Any], catalog: Optional[dict] = None) -> Dict[str, Any]:
    """Post-process a plan (from LLM or rule-based) using lightweight heuristics.

    Key goals:
    - Add time grouping for month/quarter when mentioned.
    - Add discount metrics when the question asks for discounts.
    - Infer Top-N when the question is a ranking query.
    - Keep it SAFE: only add keys that exist in the catalog.
    """
    # Backward compatible: older callers may not pass catalog (e.g., /eval/smoke)
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
        # keep monthly output bounded
        plan["limit"] = min(int(plan.get("limit") or DEFAULT_MAX_ROWS), 60)

    quarter_hit = (
        any(x in q_raw for x in ["ربع", "بالربع", "ربع سنوي", "ربع سنوية", "ربعياً", "ربعيا"])
        or any(x in q for x in ["quarter", "qtr", "quarterly"])
    )
    if quarter_hit:
        # Prefer explicit quarter/year columns if available
        add_dim("order_year")
        add_dim("order_quarter")

    # -----------------------
    # Metric intent heuristics
    # -----------------------
    net_hit = any(x in q_raw for x in ["صافي", "صافية"]) or "net" in q
    gross_hit = "إجمالي" in q_raw and not net_hit
    disc_hit = any(x in q_raw for x in ["خصم", "خصومات"]) or any(x in q for x in ["discount", "discounts"])

    # Choose the best discount metric key present in the catalog
    discount_metric = None
    for cand in ["discount_amount", "discounts", "discount"]:
        if cand in metrics_ok:
            discount_metric = cand
            break

    # If it is a "compare" style query, include multiple metrics when possible.
    if net_hit:
        add_metric("net_sales")
        # Default sort by net_sales
        plan["sort"] = [{"field": "net_sales", "dir": "desc"}] if "net_sales" in metrics_ok else (plan.get("sort") or [])
    if gross_hit:
        add_metric("gross_sales")
        if not plan.get("sort"):
            plan["sort"] = [{"field": "gross_sales", "dir": "desc"}] if "gross_sales" in metrics_ok else []
    if disc_hit and discount_metric:
        add_metric(discount_metric)

    # If question explicitly says "compare" and we have both, keep both metrics in the response.
    compare_hit = ("قارن" in q_raw) or ("compare" in q)
    if compare_hit:
        # Ensure a stable ordering: net_sales first, then discounts if requested, then others.
        ordered = []
        for k in ["net_sales", discount_metric, "gross_sales", "gross_profit"]:
            if k and k in (plan.get("metrics") or []) and k not in ordered:
                ordered.append(k)
        # add any remaining metrics (if LLM added more)
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
    if city_val:
        filters = plan.get("filters") or []
        if not any(isinstance(f, dict) and f.get("field") == "city" for f in filters):
            filters.append({"field": "city", "op": "=", "value": city_val})
        plan["filters"] = filters
        add_dim("city")

    # -----------------------
    # Top-N inference (v3)
    # -----------------------
    top_n = _infer_top_limit(question or "")
    if top_n is not None:
        plan["limit"] = min(5000, max(1, int(top_n)))

    return plan


def _catalog_hash(catalog: dict) -> str:
    payload = json.dumps(catalog, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


async def _cache_touch(cache_id: int) -> None:
    try:
        await _db_fetchval(
            """
            UPDATE bi_meta.plan_cache
            SET hits = hits + 1,
                last_used_at = now(),
                updated_at = now()
            WHERE id = $1
            RETURNING id;
            """,
            cache_id,
        )
    except Exception:
        pass


def _explain_from_rows(question: str, plan: dict, rows: List[dict]) -> dict:
    metric = (plan.get("metrics") or ["value"])[0]
    metric_label_ar = {"net_sales": "صافي المبيعات", "gross_sales": "إجمالي المبيعات", "gross_profit": "إجمالي الربح", "discounts": "الخصومات", "discount_amount": "الخصومات"}.get(metric, metric)
    metric_label_en = {"net_sales": "net sales", "gross_sales": "gross sales", "gross_profit": "gross profit", "discounts": "discounts", "discount_amount": "discounts"}.get(metric, metric)

    if not rows:
        return {
            "summary_ar": f"لا توجد نتائج مطابقة لهذا السؤال ({metric_label_ar}).",
            "summary_en": f"No results matched this query ({metric_label_en}).",
            "insights_ar": [],
            "insights_en": [],
            "followups_ar": ["جرّب تغيير الفلاتر أو توسيع الفترة الزمنية."],
            "followups_en": ["Try adjusting filters or expanding the time range."],
        }

    def _num(x):
        try:
            return float(x)
        except Exception:
            return None

    vals = [(_num(r.get(metric)), r) for r in rows]
    vals = [(v, r) for (v, r) in vals if v is not None]
    max_row = max(vals, key=lambda x: x[0])[1] if vals else rows[0]
    min_row = min(vals, key=lambda x: x[0])[1] if vals else rows[-1]

    def fmt(v):
        try:
            return f"{float(v):,.2f}"
        except Exception:
            return str(v)

    month_key = "month_start" if rows and isinstance(rows[0], dict) and "month_start" in rows[0] else None
    city = None
    for f in plan.get("filters") or []:
        if isinstance(f, dict) and f.get("field") == "city" and f.get("op") == "=":
            city = f.get("value")

    city_ar = "سيدني" if city == "Sydney" else ("ملبورن" if city == "Melbourne" else (city or ""))
    city_en = city or ""

    summary_ar = f"يعرض التقرير {metric_label_ar} " + (f"في {city_ar} " if city_ar else "") + f"لعدد {len(rows)} صف/فترة."
    summary_en = f"The report shows {metric_label_en} " + (f"for {city_en} " if city_en else "") + f"across {len(rows)} rows/periods."

    insights_ar = [
        f"أعلى قيمة كانت {fmt(max_row.get(metric))}" + (f" في {max_row.get(month_key)}." if month_key else "."),
        f"أقل قيمة كانت {fmt(min_row.get(metric))}" + (f" في {min_row.get(month_key)}." if month_key else "."),
    ]
    insights_en = [
        f"Highest value was {fmt(max_row.get(metric))}" + (f" on {max_row.get(month_key)}." if month_key else "."),
        f"Lowest value was {fmt(min_row.get(metric))}" + (f" on {min_row.get(month_key)}." if month_key else "."),
    ]

    return {
        "summary_ar": summary_ar,
        "summary_en": summary_en,
        "insights_ar": insights_ar[:3],
        "insights_en": insights_en[:3],
        "followups_ar": ["هل تريد نفس التحليل لكن حسب فئة المنتج؟", "هل تريد مقارنة سيدني وملبورن في نفس الفترة؟", "هل تريد ترتيب أفضل 10 منتجات حسب صافي المبيعات؟"],
        "followups_en": ["Do you want the same analysis broken down by product category?", "Do you want to compare Sydney vs Melbourne for the same period?", "Do you want the top 10 products by net sales?"],
    }


# -----------------------------------------------------------------------------
# /ask endpoint
# -----------------------------------------------------------------------------
router = APIRouter(prefix="/ask", tags=["ask"])

@router.post("")
async def ask(
    body: AskBody,
    explain: bool = Query(False, description="If true, return bilingual explanation + followups"),
    use_llm: bool = Query(False, description="If true, attempt Gemini (uses quota)."),
    use_cache: bool = Query(True, description="If true, use cached plan when available."),
):
    catalog = await _get_catalog()
    c_hash = _catalog_hash(catalog)
    q_norm = _normalize_question(body.question)

    plan: Optional[dict] = None
    used_cache = False
    used_llm = False
    warnings_outer: List[str] = []

    # 1) cache first
    if use_cache:
        cached = await _cache_get_plan(q_norm, c_hash, _db_fetchrow, _ensure_json_obj)
        # If cache returned a rule_based plan but caller requested LLM, ignore cache so LLM can run.
        if use_llm and cached and str(cached.get('notes','')).strip().lower() == 'rule_based':
            cached = None
            used_cache = False
        if cached and cached.get("plan"):
            plan = cached["plan"]
            used_cache = True
            # prefer LLM over cached rule_based plan when explicitly requested
            if use_llm and isinstance(plan, dict) and plan.get('notes') == 'rule_based':
                plan = None
                used_cache = False

            if cached.get("id") is not None:
                await _cache_touch(int(cached["id"]))

    # 2) if no cache, try LLM
    # قبل البلوك (مرة واحدة داخل ask())
    llm_attempted = False
    llm_error = None

# 2) if no cache, try LLM
    if plan is None and use_llm and LLM_ENABLED:
        try:
            gclient = _get_gclient()
            if gclient is None:
                raise RuntimeError("Gemini client is None")

            llm_attempted = True
            used_llm = True

            city_hint = ["Sydney", "Melbourne"]
            DEBUG_SCOPE = os.getenv("DEBUG_SCOPE", "0") in ("1", "true", "True", "yes", "YES")
            catalog_llm = _scope_catalog_for_llm(body.question, catalog)

            # (اختياري للتشخيص - تقدر تشيله بعدين)
            if DEBUG_SCOPE:
                print("CATALOG full:", len(catalog.get("metrics", [])), len(catalog.get("dimensions", [])))
                print("CATALOG scoped:", len(catalog_llm.get("metrics", [])), len(catalog_llm.get("dimensions", [])))
                print("SCOPED metrics sample:", [_item_key(x) for x in catalog_llm.get("metrics", [])[:10]])
                print("SCOPED dims sample:", [_item_key(x) for x in catalog_llm.get("dimensions", [])[:10]])


            allowed_metrics = sorted(_catalog_keys(catalog_llm, "metrics"))
            allowed_dims = sorted(_catalog_keys(catalog_llm, "dimensions"))

            prompt = f"""
    You are a STRICT query-plan generator. Return ONLY valid JSON. No explanations, no code fences.

    Catalog (filtered) JSON:
    {json.dumps(catalog_llm, ensure_ascii=False)}

    Use ONLY these keys unless absolutely necessary:
    - metrics: {", ".join(allowed_metrics)}
    - dimensions: {", ".join(allowed_dims)}

    Return JSON with this schema ONLY:
    {{
    "metrics": [],
    "dimensions": [],
    "filters": [],
    "sort": [{{"field":"", "dir":"desc"}}],
    "limit": {DEFAULT_MAX_ROWS},
    "notes": ""
    }}

    Hard rules (MUST):
    - Prefer canonical time keys when available: use "order_year" and "order_quarter" (do NOT include both "quarter" and "order_quarter").
    - Prefer metric "discount_amount" for discounts (do NOT include both "discount_amount" and "discounts").
    - If the question contains "صافي" or "صافية" -> use metric "net_sales" (NOT gross_sales).
    - If the question contains "إجمالي" -> use metric "gross_sales".
    - If the question contains "شهري" or "شهريا" or "بالشهر" -> include dimension "month_start".
    - If the question mentions a city name -> add a filter on dimension "city".
    City examples in this dataset: {city_hint}
    Arabic mapping examples: "سيدني" -> "Sydney", "ملبورن" -> "Melbourne"

    Allowed ops: =, !=, >, >=, <, <=, in, between, ilike
    filters[] must be like: {{"field":"city","op":"=","value":"Sydney"}}

    Example:
    Question: "صافي المبيعات شهريا في سيدني"
    JSON:
    {{
    "metrics": ["net_sales"],
    "dimensions": ["month_start","city"],
    "filters": [{{"field":"city","op":"=","value":"Sydney"}}],
    "sort": [{{"field":"net_sales","dir":"desc"}}],
    "limit": 60,
    "notes": ""
    }}

    Now generate the JSON plan for:
    {body.question}
    """.strip()

            try:
                resp = gclient.models.generate_content(model=GEMINI_MODEL, contents=prompt)
            except Exception as e:
                msg = str(e)
                if "503" in msg or "UNAVAILABLE" in msg:
                    time.sleep(0.35)
                    resp = gclient.models.generate_content(model=GEMINI_MODEL, contents=prompt)
                else:
                    raise
            raw = (resp.text or "").strip()
            plan = _extract_json(raw)

        except Exception as e:
            used_llm = False
            llm_error = f"{type(e).__name__}: {str(e)[:180]}"
            warnings_outer.append(f"LLM failed: {llm_error}")
            plan = None

    # 3) fallback rule-based
    if plan is None:
        plan = _rule_based_plan(body.question, catalog)

    # Normalize + heuristics + validate
    # Normalize + autocorrect + heuristics + validate
    plan, plan_corrections = finalize_plan(
    body.question,
    plan,
    catalog,
    default_max_rows=DEFAULT_MAX_ROWS,
    plan_autocorrect=PLAN_AUTOCORRECT,
    dedupe_synonyms=DEDUPE_SYNONYMS,
    allowed_ops=ALLOWED_OPS,
    max_rows_cap=int(os.getenv("MAX_ROWS_CAP", "5000")),
    )


    # Cache used plan
    if use_cache:
        model_name = GEMINI_MODEL if used_llm else "rule_based"
        await _cache_upsert_plan(q_norm, body.question, c_hash, plan, model_name, _db_fetchval)


    # -------------------------------------------------------------------------
    # Execute query (compile -> guardrails -> execute)
    #   We avoid calling bi_meta.run_query directly so we can apply python-level
    #   guardrails before execution.
    # -------------------------------------------------------------------------
    t0 = time.time()
    try:
        compiled_sql = await _db_fetchval(
            "SELECT bi_meta.compile_query($1::jsonb);",
            json.dumps(plan, ensure_ascii=False),
        )
    except Exception as e:
        # plan is invalid or metadata is missing
        raise HTTPException(status_code=400, detail=f"Plan compile failed: {e}")

    if not compiled_sql or not str(compiled_sql).strip():
        raise HTTPException(status_code=500, detail="Compiler returned empty SQL.")

    # Apply guardrails (single statement, SELECT/WITH only, schema allowlist, etc.)
    try:
        safe_sql = guard_sql_or_raise(
            str(compiled_sql),
            max_rows=int(plan.get("limit") or DEFAULT_MAX_ROWS),
            allowed_schemas={"bi"},
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"SQL blocked by guardrails: {e}")

    # Execute safely
    try:
        rows = await _db_fetch(safe_sql)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB execution failed: {e}")

    duration_ms = int((time.time() - t0) * 1000)

    sql = safe_sql
    warnings = []
    if safe_sql.strip() != str(compiled_sql).strip():
        warnings.append("Guardrails modified SQL (e.g., enforced LIMIT).")
    suggestions = {}
    # Log (non-blocking)
    log_id = None
    try:
        log_id = await _db_fetchval(
            """
            INSERT INTO bi_meta.query_log(question, plan, sql, row_count, warnings, suggestions, duration_ms, explain_used)
            VALUES ($1, $2::jsonb, $3, $4, $5::jsonb, $6::jsonb, $7, $8)
            RETURNING id;
            """,
            body.question,
            json.dumps(plan, ensure_ascii=False),
            sql,
            len(rows),
            json.dumps(warnings, ensure_ascii=False),
            json.dumps(suggestions, ensure_ascii=False),
            duration_ms,
            bool(explain),
        )
    except Exception:
        pass

    explain_obj = None
    if explain:
        if use_llm and LLM_ENABLED:
            try:
                gclient_explain = _get_gclient()
                if gclient_explain is not None:
                    prompt2 = f"""You are a bilingual BI analyst. Return ONLY valid JSON. No explanations.
                                Input:
                                - Question (Arabic): {body.question}
                                - Plan JSON: {json.dumps(plan, ensure_ascii=False)}
                                - Rows JSON (first 60): {json.dumps(rows[:60], ensure_ascii=False)}

                                Return JSON with exactly these keys:
                                {{
                                "summary_ar": "",
                                "summary_en": "",
                                "insights_ar": ["", "", ""],
                                "insights_en": ["", "", ""],
                                "followups_ar": ["", "", ""],
                                "followups_en": ["", "", ""]
                                }}""".strip()
                    resp2 = gclient_explain.models.generate_content(model=GEMINI_MODEL, contents=prompt2)
                    explain_obj = _extract_json((resp2.text or "").strip())
            except Exception:
                explain_obj = None

        if explain_obj is None:
            explain_obj = _explain_from_rows(body.question, plan, rows)

    return {
        "question": body.question,
        "plan": plan,
        "result": {
            "sql": sql,
            "rows": rows,
            "warnings": warnings_outer or None,
            "suggestions": suggestions,
        },
        "explain": explain_obj,
        "meta": {
            "ask_version": ASK_VERSION,
            "log_id": log_id,
            "used_cache": used_cache,
            "used_llm": used_llm,
            "llm_enabled": LLM_ENABLED,
            "llm_attempted": llm_attempted,
            "llm_error": llm_error,
            "duration_ms": duration_ms,
            "plan_corrections": plan_corrections,

        },
    }