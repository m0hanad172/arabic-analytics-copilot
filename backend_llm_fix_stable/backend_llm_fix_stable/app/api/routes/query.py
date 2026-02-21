from __future__ import annotations

import inspect
from typing import Any, Tuple

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import settings
from backend.app.core.sql_guardrails import guard_sql_or_raise
from backend.app.db.session import get_session
from backend.app.models.schemas import QueryRequest, QueryResponse
from backend.app.services.catalog_cache import get_catalog
from backend.app.services.query_service import run_query
from backend.app.sqlgen.translate import translate_arabic_to_sql

router = APIRouter(tags=["query"])


async def _maybe_await(x: Any) -> Any:
    """Allows calling functions that may be sync or async."""
    if inspect.isawaitable(x):
        return await x
    return x


def _unpack_translate_result(tr: Any) -> Tuple[str, str]:
    """
    translate_arabic_to_sql may return:
      - tuple: (sql, explanation)
      - dict: {"sql": "...", "explanation": "..."}
      - str:  "SELECT ..."
    """
    if isinstance(tr, tuple) and len(tr) >= 1:
        sql = tr[0]
        explanation = tr[1] if len(tr) >= 2 else ""
        return str(sql), str(explanation or "")

    if isinstance(tr, dict):
        sql = tr.get("sql", "")
        explanation = tr.get("explanation", "") or ""
        return str(sql), str(explanation)

    if isinstance(tr, str):
        return tr, ""

    raise ValueError("translate_arabic_to_sql returned an unexpected format.")


@router.post("/query", response_model=QueryResponse)
async def query(req: QueryRequest, session: AsyncSession = Depends(get_session)):
    max_rows = req.max_rows or settings.default_max_rows

    # ------------------------------------------------------------
    # 1) debug_sql (highest risk) — enforce guardrails before use
    # ------------------------------------------------------------
    if req.debug_sql:
        try:
            sql_to_execute = guard_sql_or_raise(
                req.debug_sql,
                max_rows=max_rows,
                allowed_schemas={"bi"},
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        explanation = "debug_sql (guarded)"

    # ------------------------------------------------------------
    # 2) Normal path: Arabic question -> SQL
    # ------------------------------------------------------------
    else:
        try:
            catalog = await _maybe_await(get_catalog())
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Catalog load failed: {e}")

        try:
            # Try signatures in a tolerant way
            try:
                tr = translate_arabic_to_sql(req.question, catalog=catalog, max_rows=max_rows)
            except TypeError:
                try:
                    tr = translate_arabic_to_sql(req.question, catalog=catalog)
                except TypeError:
                    tr = translate_arabic_to_sql(req.question)

            generated_sql, explanation = _unpack_translate_result(tr)
            if not generated_sql or not generated_sql.strip():
                raise ValueError("Translator returned empty SQL.")
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"Translation error: {e}")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Translator failed: {e}")

        # Guardrails also for generated SQL (defense-in-depth)
        try:
            sql_to_execute = guard_sql_or_raise(
                generated_sql,
                max_rows=max_rows,
                allowed_schemas={"bi"},
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"Generated SQL blocked: {e}")

    # ------------------------------------------------------------
    # 3) execute=false => return SQL only
    # ------------------------------------------------------------
    if not req.execute:
        return QueryResponse(sql=sql_to_execute, explanation=explanation, rows=[], row_count=0)

    # ------------------------------------------------------------
    # 4) Execute against DB
    # ------------------------------------------------------------
    try:
        try:
            rows = await run_query(session, sql_to_execute, max_rows=max_rows)
        except TypeError:
            rows = await run_query(session, sql_to_execute)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB execution failed: {e}")

    return QueryResponse(
        sql=sql_to_execute,
        explanation=explanation,
        rows=rows or [],
        row_count=len(rows) if rows else 0,
    )
