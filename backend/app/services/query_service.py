from typing import Dict, Any, List
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import settings
from backend.app.db.adapter import normalize_value
from backend.app.db.dialects import get_dialect
from backend.app.utils.sql_safety import assert_safe_select, assert_only_allowed_schema


# Backwards compatibility shim: older callers may still import
# _normalize_value from this module.
_normalize_value = normalize_value


async def run_query(session: AsyncSession, sql: str) -> List[Dict[str, Any]]:
    assert_safe_select(sql)
    assert_only_allowed_schema(sql, settings.allowed_schema)

    # Phase B: route the per-statement timeout through the active dialect
    # so SQL Server (which has no equivalent inline statement) can opt out
    # cleanly. PostgreSQL keeps emitting "SET statement_timeout = N" — same
    # behaviour as before.
    dialect = get_dialect()
    timeout_stmt = dialect.set_statement_timeout(int(settings.statement_timeout_ms))
    if timeout_stmt:
        await session.execute(text(timeout_stmt))

    result = await session.execute(text(sql))
    cols = list(result.keys())
    rows = result.fetchall()

    out: List[Dict[str, Any]] = []
    for r in rows:
        out.append({cols[i]: normalize_value(r[i]) for i in range(len(cols))})
    return out
