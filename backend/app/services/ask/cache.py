from __future__ import annotations
from .db import _db_fetchval, _db_fetchrow, _db_fetch

import re
import json
from typing import Optional


# Extracted from services/ask/runner.py (Step2)
# Cache helpers for bi_meta.plan_cache (no behavior change).

def _normalize_question(q: str) -> str:
    q = (q or "").strip().lower()
    q = re.sub(r"\s+", " ", q)
    return q
async def _cache_get_plan(question_norm: str, catalog_hash: str, db_fetchrow, ensure_json_obj) -> Optional[dict]:
    try:
        row = await db_fetchrow(
            """
            SELECT id, plan, model
            FROM bi_meta.plan_cache
            WHERE question_norm=$1 AND catalog_hash=$2
            ORDER BY updated_at DESC
            LIMIT 1;
            """,
            question_norm,
            catalog_hash,
        )
        if not row:
            return None
        row["plan"] = ensure_json_obj(row.get("plan"))
        return row
    except Exception:
        return None

async def _cache_upsert_plan(question_norm: str, question_raw: str, catalog_hash: str, plan: dict, model: str, db_fetchval) -> None:
    try:
        await db_fetchval(
            """
            INSERT INTO bi_meta.plan_cache(question_norm, question_raw, catalog_hash, plan, model, hits, last_used_at)
            VALUES ($1, $2, $3, $4::jsonb, $5, 0, now())
            ON CONFLICT (question_norm, catalog_hash)
            DO UPDATE SET
            question_raw = EXCLUDED.question_raw,
            plan        = EXCLUDED.plan,
            model       = EXCLUDED.model,
            last_used_at = now(),
            updated_at  = CASE
                WHEN bi_meta.plan_cache.plan  IS DISTINCT FROM EXCLUDED.plan
                    OR bi_meta.plan_cache.model IS DISTINCT FROM EXCLUDED.model
                THEN now()
                ELSE bi_meta.plan_cache.updated_at
            END;
            """,
            question_norm,
            question_raw,
            catalog_hash,
            json.dumps(plan, ensure_ascii=False),
            model,
        )
    except Exception:
        pass


# -----------------------------------------------------------------------------
# Explanation fallback (no LLM)
# -----------------------------------------------------------------------------
