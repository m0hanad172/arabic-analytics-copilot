"""
Database adapter (Phase B).

Single place to answer "what backend are we on?" and to host the
asyncpg-based DB helpers used by the /ask path. Centralising these so
asyncpg is no longer scattered across services/* makes Phase C
(SQL Server parity for /ask) a focused change.

Phase B is intentionally narrow:
- We expose backend identification + URL helpers + a controlled error
  type for paths that have no SQL Server implementation yet.
- The asyncpg helpers stay PostgreSQL-only. On SQL Server they raise
  BackendNotSupportedError instead of silently failing with a confusing
  "no such driver" trace.
- We do **not** build a SQLAlchemy-based replacement here. That is part
  of Phase C alongside the bi_meta.* port.
"""
from __future__ import annotations

import json
import os
from decimal import Decimal
from typing import Any, Optional

from backend.app.core.config import settings


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class BackendNotSupportedError(RuntimeError):
    """Raised when a code path has no implementation for the active backend.

    Routes should catch this and translate it to an HTTP 501 with a clear
    message; see ``controlled_backend_error_message`` for the canonical
    text used by /ask.
    """


def controlled_backend_error_message() -> str:
    """The user-facing message returned when /ask hits an unsupported
    SQL Server path. Centralised so tests and routes share one string."""
    return (
        "SQL Server dialect support exists, but /ask requires Phase C "
        "because bi_meta compile/catalog/cache/log logic is still "
        "PostgreSQL-specific."
    )


# ---------------------------------------------------------------------------
# Backend identification
# ---------------------------------------------------------------------------
_PG_ALIASES = {"postgres", "postgresql", "pg"}
_MSSQL_ALIASES = {"sqlserver", "mssql", "mssqlserver", "tsql"}


def active_backend() -> str:
    """Canonical name of the active backend: "postgres" or "sqlserver"."""
    raw = (settings.database_backend or "postgres").strip().lower()
    if raw in _MSSQL_ALIASES:
        return "sqlserver"
    if raw in _PG_ALIASES:
        return "postgres"
    # Unknown values fall back to postgres so the app keeps booting.
    return "postgres"


def is_postgres() -> bool:
    return active_backend() == "postgres"


def is_sqlserver() -> bool:
    return active_backend() == "sqlserver"


# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------
def get_database_url() -> str:
    """The active SQLAlchemy URL. Reads settings, falls back to env."""
    return settings.database_url or os.getenv("DATABASE_URL", "")


def normalize_database_url_for_asyncpg(url: str) -> str:
    """Convert a SQLAlchemy URL to a plain asyncpg DSN.

    asyncpg does not understand the ``+driver`` suffix in
    ``postgresql+asyncpg://``; strip it.
    """
    if not url:
        return url
    if url.startswith("postgresql+asyncpg://"):
        return "postgresql://" + url[len("postgresql+asyncpg://"):]
    if url.startswith("postgres+asyncpg://"):
        return "postgresql://" + url[len("postgres+asyncpg://"):]
    return url


# ---------------------------------------------------------------------------
# Row serialization
# ---------------------------------------------------------------------------
def normalize_value(v: Any) -> Any:
    """Make a single SQL value JSON-serialisable.

    Same rules as services/query_service._normalize_value, factored here
    so any backend can use it.
    """
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, float):
        return round(v, 4)
    return v


def ensure_json_obj(x: Any) -> Any:
    """asyncpg may return a dict for json/jsonb; if it returns a string,
    parse it. Keep behaviour identical to the previous local helpers."""
    if isinstance(x, str):
        try:
            return json.loads(x)
        except Exception:
            return x
    return x


# ---------------------------------------------------------------------------
# PostgreSQL-only async helpers (asyncpg)
# ---------------------------------------------------------------------------
# Imported lazily so the rest of the module is usable in environments
# without asyncpg (e.g. a future SQL Server-only deployment).
def _statement_timeout_ms() -> int:
    raw = os.getenv("STATEMENT_TIMEOUT_MS")
    if raw:
        try:
            return int(raw)
        except ValueError:
            pass
    return int(getattr(settings, "statement_timeout_ms", 8000) or 8000)


def _require_postgres(op: str) -> None:
    if not is_postgres():
        raise BackendNotSupportedError(
            f"{op} is only implemented for PostgreSQL. "
            + controlled_backend_error_message()
        )


async def pg_fetchval(sql: str, *args: Any) -> Any:
    """asyncpg fetchval. Raises BackendNotSupportedError on SQL Server."""
    _require_postgres("pg_fetchval")
    import asyncpg  # type: ignore[import-untyped]

    url = get_database_url()
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    conn = await asyncpg.connect(normalize_database_url_for_asyncpg(url))
    try:
        await conn.execute(f"SET statement_timeout = {_statement_timeout_ms()};")
        val = await conn.fetchval(sql, *args)
        return ensure_json_obj(val)
    finally:
        await conn.close()


async def pg_fetchrow(sql: str, *args: Any) -> Optional[dict]:
    _require_postgres("pg_fetchrow")
    import asyncpg  # type: ignore[import-untyped]

    url = get_database_url()
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    conn = await asyncpg.connect(normalize_database_url_for_asyncpg(url))
    try:
        await conn.execute(f"SET statement_timeout = {_statement_timeout_ms()};")
        row = await conn.fetchrow(sql, *args)
        return dict(row) if row else None
    finally:
        await conn.close()


async def pg_fetch(sql: str, *args: Any) -> list[dict]:
    _require_postgres("pg_fetch")
    import asyncpg  # type: ignore[import-untyped]

    url = get_database_url()
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    conn = await asyncpg.connect(normalize_database_url_for_asyncpg(url))
    try:
        await conn.execute(f"SET statement_timeout = {_statement_timeout_ms()};")
        recs = await conn.fetch(sql, *args)
        return [dict(r) for r in recs]
    finally:
        await conn.close()


__all__ = [
    "BackendNotSupportedError",
    "controlled_backend_error_message",
    "active_backend",
    "is_postgres",
    "is_sqlserver",
    "get_database_url",
    "normalize_database_url_for_asyncpg",
    "normalize_value",
    "ensure_json_obj",
    "pg_fetchval",
    "pg_fetchrow",
    "pg_fetch",
]
