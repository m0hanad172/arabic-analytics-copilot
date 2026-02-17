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
from pathlib import Path
from typing import Any, Optional, Dict, List, Tuple

import asyncpg
from dotenv import load_dotenv
from fastapi import HTTPException

from backend.app.core.sql_guardrails import guard_sql_or_raise
from backend.app.services.ask.catalog import _augment_catalog
from backend.app.services.ask.cache import _normalize_question, _cache_get_plan, _cache_upsert_plan
from backend.app.services.ask.plan_normalize import finalize_plan

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

# -----------------------
# Optional Gemini
# -----------------------
try:
    from google import genai  # type: ignore
except Exception:  # pragma: no cover
    genai = None

GEMINI_API_KEY = (os.getenv("GEMINI_API_KEY") or "").strip()
GEMINI_MODEL = (os.getenv("GEMINI_MODEL", "gemini-3-flash") or "").strip()
LLM_ENABLED = bool(GEMINI_API_KEY) and genai is not None

LLM_BACKOFF_SECONDS = int(os.getenv("LLM_BACKOFF_SECONDS", "600"))
_llm_disabled_until = 0.0

# ✅ IMPORTANT: eval.py expects name `gclient` exactly
gclient = None  # type: ignore


def _is_quota_error(msg: str) -> bool:
    m = (msg or "").upper()
    return ("429" in m) or ("RESOURCE_EXHAUSTED" in m) or ("QUOTA" in m) or ("RATE LIMIT" in m)


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
    if not GEMINI_API_KEY:
        gclient = None
        return None
    try:
        from google import genai as genai_new  # type: ignore
        if hasattr(genai_new, "Client"):
            gclient = genai_new.Client(api_key=GEMINI_API_KEY)
            return gclient
    except Exception:
        pass
    gclient = None
    return None


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


def _strip_sql_terminator(sql: str) -> str:
    s = (sql or "").strip()
    if not s:
        return s
    return re.sub(r";+\s*$", "", s)


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
# ✅ BACKWARD-COMPAT: eval.py/tests expect `_get_catalog` from runner.py
# ---------------------------------------------------------------------
async def _get_catalog(schema: str = "bi") -> dict:
    cat, _src = await _get_catalog_with_source(schema)
    return cat


async def _get_catalog_with_source(schema: str = "bi") -> Tuple[dict, str]:
    # Prefer catalog_cache (so meta.catalog_source works)
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

    # Fallback: DB function
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
) -> dict:
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

    # 1) cache
    if use_cache:
        cached = await _cache_get_plan(q_norm, c_hash, _db_fetchrow, _ensure_json_obj)
        if cached and cached.get("plan"):
            plan = cached["plan"]
            used_cache = True
            if cached.get("id") is not None:
                await _cache_touch(int(cached["id"]))

    # 2) optional LLM
    if plan is None and use_llm:
        if not LLM_ENABLED:
            warnings_outer.append("LLM skipped: not enabled (missing GEMINI_API_KEY or SDK).")
        elif _backoff_active():
            llm_error = "Backoff active (quota exhausted recently)"
            warnings_outer.append("LLM skipped: quota backoff active.")
        else:
            try:
                g = _get_gclient()
                if g is None:
                    raise RuntimeError("Gemini client is None")

                llm_attempted = True
                used_llm = True

                allowed_metrics = sorted(_catalog_keys(catalog, "metrics"))
                allowed_dims = sorted(_catalog_keys(catalog, "dimensions"))

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

                resp = g.models.generate_content(model=GEMINI_MODEL, contents=prompt)
                raw = (getattr(resp, "text", None) or "").strip()
                plan = _extract_json(raw)

            except Exception as e:
                used_llm = False
                msg = str(e)
                if _is_quota_error(msg):
                    _set_backoff(LLM_BACKOFF_SECONDS)
                llm_error = f"{type(e).__name__}: {msg[:180]}"
                warnings_outer.append(f"LLM failed: {llm_error}")
                plan = None

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
    compiled_for_guard = _strip_sql_terminator(compiled_sql_raw)

    try:
        safe_sql = guard_sql_or_raise(
            compiled_for_guard,
            max_rows=int(plan.get("limit") or DEFAULT_MAX_ROWS),
            allowed_schemas={"bi"},
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"SQL blocked by guardrails: {e}")

    safe_sql = _ensure_single_sql_terminator(str(safe_sql))
    rows = await _db_fetch(safe_sql)

    duration_ms = int((time.time() - t0) * 1000)

    warnings_exec: List[str] = []
    if _strip_sql_terminator(safe_sql) != _strip_sql_terminator(compiled_sql_raw):
        warnings_exec.append("Guardrails modified SQL (e.g., enforced LIMIT).")

    warnings_all = [*warnings_outer, *warnings_exec]
    suggestions: Dict[str, Any] = {}

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
        "explain": None,
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
            "catalog_source": catalog_source,
            "catalog_hash": c_hash,
        },
    }
