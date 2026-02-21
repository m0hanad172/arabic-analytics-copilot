"""
Arabic Analytics Copilot - ask runner (backward-compatible)

Path:
  backend/app/services/ask/runner.py

Must keep old symbols for eval.py + tests:
  _get_catalog, gclient,
  _validate_plan, _normalize_plan, _rule_based_plan, _infer_top_limit, _apply_heuristics,
  ALLOWED_OPS, _catalog_keys, _ARABIC_DIGIT_MAP
"""

from __future__ import annotations

import os
import re
import json
import time
import hashlib
import asyncio
from pathlib import Path
from typing import Any, Optional, Dict, List, Tuple

import asyncpg
from dotenv import load_dotenv
from fastapi import HTTPException

from backend.app.core.sql_guardrails import guard_sql_or_raise
from backend.app.services.ask.catalog import _augment_catalog
from backend.app.services.ask.cache import _normalize_question, _cache_get_plan, _cache_upsert_plan
from backend.app.services.ask.plan_normalize import finalize_plan

from backend.app.services.ask.llm_client import (
    llm_enabled as _llm_enabled,
    get_gemini_client as _get_gemini_client_new,
    call_gemini_with_budget,
    is_quota_error as _is_quota_error_new,
    GEMINI_MODEL,
)

LLM_BACKOFF_SECONDS_QUOTA = int(os.getenv("LLM_BACKOFF_SECONDS_QUOTA", "30"))
LLM_BACKOFF_SECONDS_TIMEOUT = int(os.getenv("LLM_BACKOFF_SECONDS_TIMEOUT", "3"))

# -----------------------------
# plan_core: source of truth
# -----------------------------
from backend.app.services.ask.plan_core import (  # noqa: F401
    _validate_plan,
    _normalize_plan,
    _rule_based_plan,
    _infer_top_limit,
    _apply_heuristics,
    ALLOWED_OPS,
    _catalog_keys,
    _ARABIC_DIGIT_MAP,
)

ASK_VERSION = "v4.7"

# -----------------------
# ENV
# -----------------------
ENV_PATH = Path(__file__).resolve().parents[3] / ".env"
load_dotenv(ENV_PATH)

DATABASE_URL = os.getenv("DATABASE_URL", "")
STATEMENT_TIMEOUT_MS = int(os.getenv("STATEMENT_TIMEOUT_MS", "8000"))
DEFAULT_MAX_ROWS = int(os.getenv("DEFAULT_MAX_ROWS", "200"))

DEDUPE_SYNONYMS = os.getenv("DEDUPE_SYNONYMS", "0") in ("1", "true", "True", "yes", "YES")
PLAN_AUTOCORRECT = os.getenv("PLAN_AUTOCORRECT", "1") in ("1", "true", "True", "yes", "YES")

# ✅ Reduce prompt size to improve LLM latency (non-breaking)
LLM_MAX_KEYS_IN_PROMPT = int(os.getenv("LLM_MAX_KEYS_IN_PROMPT", "60"))

# -----------------------
# LLM (Gemini) via llm_client.py
# -----------------------
LLM_ENABLED = _llm_enabled()

LLM_BACKOFF_SECONDS = int(os.getenv("LLM_BACKOFF_SECONDS", "30"))
_llm_disabled_until = 0.0

# ✅ IMPORTANT: eval.py expects name `gclient` exactly
gclient = None  # type: ignore


def _is_quota_error(msg: str) -> bool:
    return _is_quota_error_new(msg)


def _backoff_active() -> bool:
    return time.time() < _llm_disabled_until


def _set_backoff(seconds: int) -> None:
    global _llm_disabled_until
    _llm_disabled_until = time.time() + max(0, int(seconds))


def _get_gclient():
    """Lazy init Gemini client. Keeps backward-compatible global `gclient`."""
    global gclient
    if gclient is not None:
        return gclient
    gclient = _get_gemini_client_new()
    return gclient


# -----------------------
# catalog_cache (preferred)
# -----------------------
_load_catalog = None
try:
    from backend.app.services.catalog_cache import load_catalog as _load_catalog  # type: ignore
except Exception:
    try:
        from backend.app.services.catalog_cache import get_catalog as _load_catalog  # type: ignore
    except Exception:
        _load_catalog = None

try:
    from backend.app.services.catalog_cache import get_catalog_source  # type: ignore
except Exception:
    def get_catalog_source() -> str:  # type: ignore
        return "unknown"


# -----------------------
# DB helpers
# -----------------------
def _asyncpg_dsn(sqlalchemy_url: str) -> str:
    return sqlalchemy_url.replace("postgresql+asyncpg://", "postgresql://", 1)


def _ensure_json_obj(x: Any) -> Any:
    if isinstance(x, str):
        try:
            return json.loads(x)
        except Exception:
            return x
    return x


async def _db_fetchval(sql: str, *args) -> Any:
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set in backend/.env")
    conn = await asyncpg.connect(_asyncpg_dsn(DATABASE_URL))
    try:
        await conn.execute(f"SET statement_timeout = {STATEMENT_TIMEOUT_MS};")
        val = await conn.fetchval(sql, *args)
        return _ensure_json_obj(val)
    finally:
        await conn.close()


async def _db_fetchrow(sql: str, *args) -> Optional[dict]:
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set in backend/.env")
    conn = await asyncpg.connect(_asyncpg_dsn(DATABASE_URL))
    try:
        await conn.execute(f"SET statement_timeout = {STATEMENT_TIMEOUT_MS};")
        row = await conn.fetchrow(sql, *args)
        return dict(row) if row else None
    finally:
        await conn.close()


async def _db_fetch(sql: str, *args) -> List[dict]:
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set in backend/.env")
    conn = await asyncpg.connect(_asyncpg_dsn(DATABASE_URL))
    try:
        await conn.execute(f"SET statement_timeout = {STATEMENT_TIMEOUT_MS};")
        recs = await conn.fetch(sql, *args)
        return [dict(r) for r in recs]
    finally:
        await conn.close()


def _catalog_hash(catalog: dict) -> str:
    payload = json.dumps(
        catalog,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


async def _cache_touch(cache_id: int) -> None:
    try:
        await _db_fetchval(
            """
            UPDATE bi_meta.plan_cache
            SET hits = COALESCE(hits, 0) + 1,
                last_used_at = now()
            WHERE id = $1
            RETURNING id;
            """,
            int(cache_id),
        )
    except Exception:
        pass


# robust trailing cleanup (handles ;; + whitespace + some bidi marks)
_TRAILING_SQL = re.compile(r"[;\s\u200e\u200f\u202a-\u202e]+$")


def _strip_sql_terminator(sql: str) -> str:
    s = (sql or "").strip()
    if not s:
        return s
    return _TRAILING_SQL.sub("", s)


def _ensure_single_sql_terminator(sql: str) -> str:
    s = _strip_sql_terminator(sql)
    return (s + ";") if s else s


def _extract_json(text: str) -> Dict[str, Any]:
    if not text:
        raise ValueError("Empty LLM response")
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\s*```$", "", t)

    try:
        obj = json.loads(t)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass

    m = re.search(r"\{.*\}", t, flags=re.DOTALL)
    if not m:
        raise ValueError("No JSON object found in LLM output")

    obj = json.loads(m.group(0))
    if not isinstance(obj, dict):
        raise ValueError("JSON is not an object")
    return obj


# ---------------------------------------------------------------------
# ✅ Top-N per year rewrite (non-breaking, only when explicitly asked)
# ---------------------------------------------------------------------
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _safe_ident(x: Any) -> str:
    s = str(x or "").strip()
    return s if _IDENT_RE.match(s) else ""


def _detect_top_per_year(question: str) -> Optional[int]:
    q = (question or "").strip()
    # must contain "per year" intent
    if not re.search(r"(?:في|لكل)\s+(?:كل\s+)?سنة", q):
        return None
    # must contain explicit top N
    m = re.search(r"(?:أعلى|افضل|أفضل|top)\s*(\d+)", q, flags=re.IGNORECASE)
    if not m:
        return None
    try:
        n = int(m.group(1))
        return max(1, n)
    except Exception:
        return None


def _is_time_dim(dim: str) -> bool:
    d = (dim or "").lower()
    return (
        d in {"order_year", "order_quarter", "order_month", "order_week", "order_day", "order_date"}
        or any(k in d for k in ["year", "quarter", "month", "week", "day", "date"])
    )


def _infer_entity_dim_for_top_per_year(question: str, dims: List[str]) -> str:
    q = (question or "")
    dset = set(dims or [])

    # Arabic hints
    if re.search(r"(?:مدينة|مدن)", q) and "city" in dset:
        return "city"
    if re.search(r"(?:منتج|منتجات)", q):
        if "product_name" in dset:
            return "product_name"
        if "product_category" in dset:
            return "product_category"
    if re.search(r"(?:فئة|تصنيف)", q) and "product_category" in dset:
        return "product_category"

    # fallback: first non-time dim (excluding year itself)
    for d in dims:
        if d == "order_year":
            continue
        if not _is_time_dim(d):
            return d

    # as last resort
    for d in dims:
        if d != "order_year":
            return d
    return ""


def _strip_trailing_order_limit(sql: str) -> str:
    s = _strip_sql_terminator(sql)
    # remove trailing LIMIT
    s = re.sub(r"\s+LIMIT\s+\d+\s*$", "", s, flags=re.IGNORECASE)
    # remove trailing ORDER BY (if it's at the end)
    s = re.sub(r"\s+ORDER\s+BY\s+[\s\S]*$", "", s, flags=re.IGNORECASE)
    return s.strip()


def _wrap_top_n_per_year(base_sql: str, n: int, entity_dim: str, metric: str, has_quarter: bool) -> str:
    core = _strip_trailing_order_limit(base_sql)
    order_extra = ", order_quarter ASC" if has_quarter else ""

    return f"""
WITH base AS (
  {core}
),
ranked AS (
  SELECT
    order_year,
    {entity_dim} AS __entity,
    SUM(COALESCE({metric}, 0)) AS __rank_value,
    ROW_NUMBER() OVER (
      PARTITION BY order_year
      ORDER BY SUM(COALESCE({metric}, 0)) DESC
    ) AS __rn
  FROM base
  GROUP BY order_year, {entity_dim}
)
SELECT *
FROM base
WHERE (order_year, {entity_dim}) IN (
  SELECT order_year, __entity
  FROM ranked
  WHERE __rn <= {int(n)}
)
ORDER BY order_year ASC{order_extra}, COALESCE({metric}, 0) DESC, {entity_dim} ASC
""".strip()


# ---------------------------------------------------------------------
# ✅ Explain (rule-based, bilingual)
# ---------------------------------------------------------------------
def _fmt_val(v: Any) -> str:
    if v is None:
        return "—"
    if isinstance(v, (dict, list)):
        try:
            return json.dumps(v, ensure_ascii=False)
        except Exception:
            return str(v)
    s = str(v).strip()
    return s if s else "—"


def _fmt_fields_list(items: Any) -> str:
    if not items:
        return "—"
    if not isinstance(items, list):
        return _fmt_val(items)

    out: List[str] = []
    for it in items:
        if isinstance(it, str):
            s = it.strip()
            if s:
                out.append(s)
        elif isinstance(it, dict):
            s = (
                it.get("field")
                or it.get("key")
                or it.get("name")
                or it.get("metric_key")
                or it.get("dim_key")
            )
            if s:
                out.append(str(s).strip())
        else:
            out.append(str(it).strip())

    out = [x for x in out if x]
    return ", ".join(out) if out else "—"


def _fmt_filters(filters: Any, lang: str) -> str:
    if not filters or not isinstance(filters, list):
        return "لا يوجد" if lang == "ar" else "none"

    parts: List[str] = []
    for f in filters:
        if not isinstance(f, dict):
            continue
        field = str(f.get("field") or "").strip()
        op = str(f.get("op") or "").strip()
        val = _fmt_val(f.get("value"))
        if not field or not op:
            continue
        parts.append(f"{field} {op} {val}".strip())

    if not parts:
        return "لا يوجد" if lang == "ar" else "none"
    return "، ".join(parts) if lang == "ar" else ", ".join(parts)


def _fmt_sort(sort: Any) -> str:
    if not sort or not isinstance(sort, list):
        return "—"
    s0 = sort[0] if sort else None
    if not isinstance(s0, dict):
        return "—"
    field = str(s0.get("field") or "").strip()
    dir_ = str(s0.get("dir") or "").strip()
    out = f"{field} {dir_}".strip()
    return out or "—"


def _build_explain_obj(
    question: str,
    plan: dict,
    sql: str,
    row_count: int,
    warnings: Optional[List[str]] = None,
) -> dict:
    metrics = _fmt_fields_list(plan.get("metrics"))
    dims = _fmt_fields_list(plan.get("dimensions"))
    filters = plan.get("filters") or []
    limit = _fmt_val(plan.get("limit"))
    sort_txt = _fmt_sort(plan.get("sort"))
    notes = str(plan.get("notes") or "").strip()

    summary_ar = (
        f"السؤال: {question}\n"
        f"المقاييس: {metrics}\n"
        f"الأبعاد: {dims}\n"
        f"الفلاتر: {_fmt_filters(filters, 'ar')}\n"
        f"الترتيب: {sort_txt}\n"
        f"الحد: {limit}\n"
        f"عدد الصفوف: {row_count}"
        + (f"\nملاحظات: {notes}" if notes else "")
    )

    summary_en = (
        f"Question: {question}\n"
        f"Metrics: {metrics}\n"
        f"Dimensions: {dims}\n"
        f"Filters: {_fmt_filters(filters, 'en')}\n"
        f"Sort: {sort_txt}\n"
        f"Limit: {limit}\n"
        f"Row count: {row_count}"
        + (f"\nNotes: {notes}" if notes else "")
    )

    insights_en: List[str] = []
    insights_ar: List[str] = []

    if metrics != "—" and dims != "—":
        insights_en.append(f"Aggregated {metrics} by {dims}.")
        insights_ar.append(f"تم تجميع {metrics} حسب {dims}.")
    if filters and isinstance(filters, list) and len(filters) > 0:
        insights_en.append(f"Applied {len(filters)} filter(s).")
        insights_ar.append(f"تم تطبيق {len(filters)} فلتر/فلاتر.")
    else:
        insights_en.append("No filters applied.")
        insights_ar.append("لا توجد فلاتر.")
    if sort_txt != "—":
        insights_en.append(f"Sorted by {sort_txt}.")
        insights_ar.append(f"الترتيب حسب: {sort_txt}.")
    insights_en.append(f"Returned {row_count} row(s).")
    insights_ar.append(f"عدد الصفوف: {row_count}.")

    followups_ar = [
        "اعرض نفس التحليل حسب السنة.",
        "غيّر Top N إلى 10 واعرض أعلى النتائج.",
        "أضف فلتر (مدينة/ولاية) محددة ثم أعد التشغيل.",
    ]
    followups_en = [
        "Show the same analysis by year.",
        "Change Top N to 10 and show the top results.",
        "Add a filter (city/state) and rerun.",
    ]

    return {
        "sql": sql,
        "row_count": row_count,
        "warnings": warnings or [],
        "en": {"summary": summary_en, "insights": insights_en, "followups": followups_en},
        "ar": {"summary": summary_ar, "insights": insights_ar, "followups": followups_ar},
        # legacy keys (safe for back-compat)
        "text_en": f"**Query summary**\n{summary_en}",
        "text_ar": f"**ملخص الاستعلام**\n{summary_ar}",
        "followups": followups_ar,
    }


# ---------------------------------------------------------------------
# ✅ BACKWARD-COMPAT: eval.py/tests expect `_get_catalog` from runner.py
# ---------------------------------------------------------------------
async def _get_catalog(schema: str = "bi") -> dict:
    cat, _src = await _get_catalog_with_source(schema)
    return cat


async def _get_catalog_with_source(schema: str = "bi") -> Tuple[dict, str]:
    if _load_catalog is not None:
        try:
            try:
                cat = await _load_catalog(schema)  # type: ignore[misc]
            except TypeError:
                cat = await _load_catalog()  # type: ignore[misc]
            if not isinstance(cat, dict) or not cat:
                raise ValueError("Empty/non-dict catalog from catalog_cache")
            cat = _augment_catalog(cat)
            src = "unknown"
            try:
                src = str(get_catalog_source() or "unknown")
            except Exception:
                src = "unknown"
            return cat, src
        except Exception:
            pass

    try:
        cat = await _db_fetchval("SELECT bi_meta.get_catalog($1)::jsonb;", schema)
        src = "db_function"
    except Exception:
        cat = await _db_fetchval("SELECT bi_meta.get_catalog();")
        src = "db_function"

    if not cat or not isinstance(cat, dict):
        raise HTTPException(status_code=500, detail="Catalog is empty or invalid JSON object.")

    return _augment_catalog(cat), src


# ---------------------------------------------------------------------
# Main runner function used by /api/routes/ask.py
# ---------------------------------------------------------------------
async def ask(
    body: Any,
    explain: bool = False,
    use_llm: bool = False,
    use_cache: bool = True,
    llm_mode: str = "",
) -> dict:

    t_all = time.time()  # ✅ total wall time (includes LLM)
    question = getattr(body, "question", None) or ""
    if not str(question).strip():
        raise HTTPException(status_code=422, detail="question is required")

    catalog, catalog_source = await _get_catalog_with_source("bi")
    c_hash = _catalog_hash(catalog)
    q_norm = _normalize_question(str(question))

    plan: Optional[dict] = None
    used_cache = False
    used_llm = False
    llm_attempted = False
    llm_error: Optional[str] = None
    warnings_outer: List[str] = []
    llm_mode_norm = (llm_mode or "").strip().lower()


    # 1) cache
    if use_cache:
        cached = await _cache_get_plan(q_norm, c_hash, _db_fetchrow, _ensure_json_obj)
        if cached and cached.get("plan"):
            plan = cached["plan"]
            used_cache = True
            if cached.get("id") is not None:
                await _cache_touch(int(cached["id"]))

    # 2) optional LLM
    llm_ms: Optional[int] = None
    llm_attempts: Optional[int] = None
    llm_status: Optional[str] = None

        # ✅ Mock LLM mode: simulate "LLM success" without external calls (non-breaking)
    if plan is None and use_llm and llm_mode_norm == "mock":
        llm_attempted = True
        used_llm = True
        llm_status = "mock"
        llm_attempts = 1
        llm_ms = 0

        plan = _rule_based_plan(str(question), catalog)
        if isinstance(plan, dict):
            # only affects mock mode
            base_note = str(plan.get("notes") or "rule_based").strip()
            plan["notes"] = (base_note + " | mock_llm").strip()


    if plan is None and use_llm:
        if not LLM_ENABLED:
            warnings_outer.append("LLM skipped: not enabled (missing GEMINI_API_KEY or SDK).")
            llm_status = "disabled"
        elif _backoff_active():
            llm_error = "Backoff active (recent quota/timeout)"
            warnings_outer.append("LLM skipped: backoff active.")
            llm_status = "backoff"
        else:
            llm_attempted = True
            try:
                g = _get_gclient()
                if g is None:
                    raise RuntimeError("Gemini client is None")

                # ✅ Trim catalog keys in prompt to reduce latency (non-breaking)
                all_metrics = sorted(_catalog_keys(catalog, "metrics"))
                all_dims = sorted(_catalog_keys(catalog, "dimensions"))

                allowed_metrics = all_metrics[: max(1, LLM_MAX_KEYS_IN_PROMPT)]
                allowed_dims = all_dims[: max(1, LLM_MAX_KEYS_IN_PROMPT)]

                if len(all_metrics) > len(allowed_metrics) or len(all_dims) > len(allowed_dims):
                    warnings_outer.append(
                        f"LLM prompt catalog keys truncated to {LLM_MAX_KEYS_IN_PROMPT} per type for speed."
                    )

                prompt = f"""
You are a STRICT query-plan generator. Return ONLY valid JSON. No explanations, no code fences.

Catalog keys:
- metrics: {", ".join(allowed_metrics)}
- dimensions: {", ".join(allowed_dims)}

Return JSON with exactly this schema:
{{
  "metrics": [],
  "dimensions": [],
  "filters": [],
  "sort": [{{"field":"", "dir":"desc"}}],
  "limit": {DEFAULT_MAX_ROWS},
  "notes": ""
}}

Hard rules:
- Allowed ops: =, !=, >, >=, <, <=, in, between, ilike

Now generate the JSON plan for:
{question}
""".strip()

                res = await call_gemini_with_budget(g, prompt)
                llm_model_name = getattr(res, "model", "") or GEMINI_MODEL
                llm_ms = res.ms
                llm_attempts = res.attempts
                llm_status = res.status

                if res.status == "ok":
                    plan = _extract_json(res.text)
                    used_llm = True
                else:
                    plan = None
                    used_llm = False
                    llm_error = f"{res.status}: {res.error}"
                    warnings_outer.append(f"LLM failed: {llm_error}")

                    if res.status == "quota":
                        _set_backoff(LLM_BACKOFF_SECONDS_QUOTA)
                    elif res.status == "timeout":
                        _set_backoff(LLM_BACKOFF_SECONDS_TIMEOUT)

            except Exception as e:
                used_llm = False
                plan = None
                msg = str(e)
                if _is_quota_error(msg):
                    _set_backoff(LLM_BACKOFF_SECONDS)
                    llm_status = "quota"
                else:
                    llm_status = "error"
                llm_error = f"{type(e).__name__}: {msg[:180]}"
                warnings_outer.append(f"LLM failed: {llm_error}")

    # 3) rule-based fallback
    if plan is None:
        plan = _rule_based_plan(str(question), catalog)

    # normalize/autocorrect/validate
    plan, plan_corrections = finalize_plan(
        str(question),
        plan,
        catalog,
        default_max_rows=DEFAULT_MAX_ROWS,
        plan_autocorrect=PLAN_AUTOCORRECT,
        dedupe_synonyms=DEDUPE_SYNONYMS,
        allowed_ops=ALLOWED_OPS,
        max_rows_cap=int(os.getenv("MAX_ROWS_CAP", "5000")),
    )

    # cache if newly generated
    if use_cache and not used_cache:
        if used_llm and llm_mode_norm == "mock":
            model_name = "mock"
        else:
            model_name = GEMINI_MODEL if used_llm else "rule_based"

        await _cache_upsert_plan(q_norm, str(question), c_hash, plan, model_name, _db_fetchval)


    # compile -> guardrails -> execute
    t0 = time.time()
    try:
        compiled_sql = await _db_fetchval(
            "SELECT bi_meta.compile_query($1::jsonb);",
            json.dumps(plan, ensure_ascii=False),
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Plan compile failed: {e}")

    if not compiled_sql or not str(compiled_sql).strip():
        raise HTTPException(status_code=500, detail="Compiler returned empty SQL.")

    compiled_sql_raw = str(compiled_sql)
    sql_for_guard = _strip_sql_terminator(compiled_sql_raw)

    # ✅ Non-breaking: apply Top-N per year ONLY if explicitly requested
    top_per_year_n = _detect_top_per_year(str(question))
    top_per_year_applied = False
    if top_per_year_n:
        dims_list = plan.get("dimensions") or []
        metrics_list = plan.get("metrics") or []
        sort_list = plan.get("sort") or []

        if isinstance(dims_list, list) and isinstance(metrics_list, list):
            if "order_year" in dims_list and len(metrics_list) > 0:
                entity_dim = _infer_entity_dim_for_top_per_year(str(question), [str(x) for x in dims_list])
                entity_dim = _safe_ident(entity_dim)

                # ranking metric: prefer sort.field else first metric
                sort_metric = ""
                if isinstance(sort_list, list) and sort_list and isinstance(sort_list[0], dict):
                    sort_metric = str(sort_list[0].get("field") or "").strip()
                if not sort_metric:
                    sort_metric = str(metrics_list[0]).strip()
                sort_metric = _safe_ident(sort_metric)

                if entity_dim and sort_metric and entity_dim in set(dims_list):
                    sql_for_guard = _wrap_top_n_per_year(
                        sql_for_guard,
                        n=int(top_per_year_n),
                        entity_dim=entity_dim,
                        metric=sort_metric,
                        has_quarter=("order_quarter" in set(dims_list)),
                    )
                    top_per_year_applied = True

    # Guardrails: default max_rows from plan.limit,
    # but for per-year we must allow more rows (N * years * maybe quarters)
    max_rows_guard = int(plan.get("limit") or DEFAULT_MAX_ROWS)
    if top_per_year_applied:
        max_cap = int(os.getenv("MAX_ROWS_CAP", "5000"))
        max_rows_guard = min(max_cap, max(DEFAULT_MAX_ROWS, int(top_per_year_n) * 200))

    try:
        safe_sql = guard_sql_or_raise(
            sql_for_guard,
            max_rows=max_rows_guard,
            allowed_schemas={"bi"},
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"SQL blocked by guardrails: {e}")

    # ✅ final normalization (kills ;; permanently)
    # ✅ FINAL normalization: absolutely prevent ';;' (strong)
    safe_sql = str(safe_sql).strip()
    safe_sql = re.sub(r"[;\s\u200e\u200f\u202a-\u202e]+$", "", safe_sql)  # remove ALL trailing ;/spaces/bidi
    safe_sql = _ensure_single_sql_terminator(safe_sql)
    safe_sql = re.sub(r";{2,}\s*$", ";", safe_sql)  # extra safety

    rows = await _db_fetch(safe_sql)
    duration_ms = int((time.time() - t0) * 1000)  # compile+guard+db only
    total_ms = int((time.time() - t_all) * 1000)  # ✅ includes LLM

    warnings_exec: List[str] = []
    if _strip_sql_terminator(safe_sql) != _strip_sql_terminator(compiled_sql_raw):
        warnings_exec.append("Guardrails or post-processing modified SQL (e.g., enforced LIMIT or Top-N per group).")
    if top_per_year_applied:
        warnings_exec.append("Applied Top-N per year logic via window function (ROW_NUMBER partition by order_year).")

    warnings_all = [*warnings_outer, *warnings_exec]
    suggestions: Dict[str, Any] = {}

    explain_obj = (
        _build_explain_obj(str(question), plan, safe_sql, len(rows), warnings_all)
        if explain
        else None
    )

    log_id = None
    try:
        log_id = await _db_fetchval(
            """
            INSERT INTO bi_meta.query_log(
                question, plan, sql, row_count, warnings, suggestions, duration_ms,
                used_cache, used_llm, explain_used
            )
            VALUES ($1, $2::jsonb, $3, $4, $5::jsonb, $6::jsonb, $7, $8, $9, $10)
            RETURNING id;
            """,
            str(question),
            json.dumps(plan, ensure_ascii=False),
            safe_sql,
            len(rows),
            json.dumps(warnings_all, ensure_ascii=False),
            json.dumps(suggestions, ensure_ascii=False),
            duration_ms,
            bool(used_cache),
            bool(used_llm),
            bool(explain),
        )
    except Exception:
        pass

    return {
        "question": str(question),
        "plan": plan,
        "result": {
            "sql": safe_sql,
            "rows": rows,
            "warnings": warnings_all or None,
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
            "duration_ms": duration_ms,   # legacy: db/compile time
            "total_ms": total_ms,         # ✅ new: total wall time including LLM
            "llm_model": ("mock" if (use_llm and llm_mode_norm == "mock") else (llm_model_name if use_llm else None)),
            "llm_ms": llm_ms,
            "llm_status": llm_status,
            "llm_attempts": llm_attempts,
            "plan_corrections": plan_corrections,
            "catalog_source": catalog_source,
            "catalog_hash": c_hash,
            "explain_used": bool(explain),
            "explain_mode": ("rule" if explain else None),
        },
    }
