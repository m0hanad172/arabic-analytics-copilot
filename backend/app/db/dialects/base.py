"""
SQL dialect interface (Phase A).

Goal: make SQL generation pluggable so we can target both PostgreSQL and
Microsoft SQL Server without duplicating the rule-based translator.

Phase A is intentionally narrow:
- We expose only the fragments that translate.py and the guardrails
  currently need.
- The Postgres dialect must emit exactly the same SQL strings the
  project produces today (no behavior change when DATABASE_BACKEND=postgres).
- The SQL Server dialect produces T-SQL-compatible fragments. It is not
  yet wired through /ask (that path depends on bi_meta.* stored functions
  which still live only in PostgreSQL).
"""
from __future__ import annotations

from typing import Optional


class SqlDialect:
    """Abstract dialect. Subclasses must implement every method below."""

    name: str = "base"

    # ---- LIMIT / TOP ----
    def limit_clause(self, n: int) -> str:
        """Return the *clause* that constrains row count (no leading space)."""
        raise NotImplementedError

    def apply_limit(self, sql: str, n: int) -> str:
        """Apply a row limit to a complete SELECT statement.

        Postgres: append "LIMIT n".
        SQL Server: inject "TOP (n)" after the leading SELECT keyword.
        """
        raise NotImplementedError

    # ---- aggregates / casts ----
    def bigint_count(self) -> str:
        """SQL fragment for a 64-bit COUNT(*) expression (no alias)."""
        raise NotImplementedError

    def cast_numeric(self, expr: str) -> str:
        """Cast an expression to a high-precision numeric type."""
        raise NotImplementedError

    # ---- identifiers / operators ----
    def quote_ident(self, ident: str) -> str:
        raise NotImplementedError

    def ilike(self, column: str, pattern_param: str) -> str:
        """Case-insensitive LIKE expression. pattern_param is the bound
        parameter placeholder/literal, already quoted by the caller."""
        raise NotImplementedError

    # ---- runtime helpers ----
    def now(self) -> str:
        raise NotImplementedError

    def nulls_last(self, direction: str = "DESC") -> str:
        """Order-by suffix to push NULLs to the end. SQL Server has no
        NULLS LAST; we emulate with a CASE expression added to ORDER BY."""
        raise NotImplementedError

    def set_statement_timeout(self, ms: int) -> Optional[str]:
        """Return a statement that sets a per-session statement timeout, or
        None if the dialect has no equivalent we want to issue inline."""
        raise NotImplementedError


def get_dialect(name: Optional[str] = None) -> SqlDialect:
    """Resolve a dialect by name. Defaults to the value in settings."""
    if name is None:
        # Local import to avoid a hard dependency cycle with config.
        from backend.app.core.config import settings
        name = settings.database_backend

    n = (name or "postgres").strip().lower()
    if n in ("postgres", "postgresql", "pg"):
        from backend.app.db.dialects.postgres import PostgresDialect
        return PostgresDialect()
    if n in ("sqlserver", "mssql", "mssqlserver", "tsql"):
        from backend.app.db.dialects.sqlserver import SqlServerDialect
        return SqlServerDialect()
    raise ValueError(f"Unknown DATABASE_BACKEND: {name!r}")
