from fastapi import APIRouter, Query, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.session import get_session

router = APIRouter(prefix="/logs", tags=["logs"])

@router.get("")
async def get_logs(
    limit: int = Query(50, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
):
    q = text("""
        SELECT id, created_at, question, row_count, duration_ms, explain_used
        FROM bi_meta.query_log
        ORDER BY id DESC
        LIMIT :limit
    """)
    res = await session.execute(q, {"limit": limit})
    rows = [dict(r._mapping) for r in res.fetchall()]
    return {"limit": limit, "rows": rows}

@router.get("/{log_id}")
async def get_log(
    log_id: int,
    session: AsyncSession = Depends(get_session),
):
    q = text("""
        SELECT id, created_at, question, plan, sql, row_count, warnings, suggestions, duration_ms, explain_used
        FROM bi_meta.query_log
        WHERE id = :id
    """)
    res = await session.execute(q, {"id": log_id})
    row = res.fetchone()
    if not row:
        return {"error": "not_found", "id": log_id}
    return dict(row._mapping)
