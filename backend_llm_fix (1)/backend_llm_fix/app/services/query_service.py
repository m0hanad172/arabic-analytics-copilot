from typing import Dict, Any, List
from decimal import Decimal
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import settings
from backend.app.utils.sql_safety import assert_safe_select, assert_only_allowed_schema

def _normalize_value(v):
    # Convert Decimals cleanly and round floats to 4 dp to avoid 0.999999 noise
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, float):
        return round(v, 4)
    return v

async def run_query(session: AsyncSession, sql: str) -> List[Dict[str, Any]]:
    assert_safe_select(sql)
    assert_only_allowed_schema(sql, settings.allowed_schema)

    await session.execute(text(f"SET statement_timeout = {int(settings.statement_timeout_ms)}"))

    result = await session.execute(text(sql))
    cols = list(result.keys())
    rows = result.fetchall()

    out: List[Dict[str, Any]] = []
    for r in rows:
        out.append({cols[i]: _normalize_value(r[i]) for i in range(len(cols))})
    return out
