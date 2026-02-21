from __future__ import annotations

from typing import Any, Optional

# NOTE:
# This is a SAFE facade to avoid circular imports.
# We keep the real DB helpers in runner.py for now, but expose them here via lazy imports.
# Later, we can move the actual DB layer into this module cleanly.

async def _db_fetchval(sql: str, *args) -> Any:
    from .runner import _db_fetchval as impl
    return await impl(sql, *args)

async def _db_fetchrow(sql: str, *args) -> Optional[dict]:
    from .runner import _db_fetchrow as impl
    return await impl(sql, *args)

async def _db_fetch(sql: str, *args) -> list[dict]:
    from .runner import _db_fetch as impl
    return await impl(sql, *args)
