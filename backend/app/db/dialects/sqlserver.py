"""Microsoft SQL Server (T-SQL) dialect.

Phase A: provides T-SQL fragments only. Not yet wired into the /ask path
(which still depends on PostgreSQL-resident bi_meta.* functions).
"""
from __future__ import annotations

import re
from typing import Optional

from backend.app.db.dialects.base import SqlDialect


_SELECT_HEAD_RE = re.compile(
    r"^(\s*)(SELECT)(\s+DISTINCT)?\b",
    flags=re.IGNORECASE,
)


class SqlServerDialect(SqlDialect):
    name = "sqlserver"

    # ---- LIMIT / TOP ----
    def limit_clause(self, n: int) -> str:
        # SQL Server has no trailing LIMIT clause. We expose TOP (n) so
        # callers that want a fragment can still get one.
        return f"TOP ({int(n)})"

    def apply_limit(self, sql: str, n: int) -> str:
        # Inject "TOP (n)" after the leading SELECT [DISTINCT] keyword.
        core = sql.rstrip().rstrip(";").rstrip()
        n_int = int(n)

        m = _SELECT_HEAD_RE.match(core)
        if not m:
            # Not a SELECT we recognise — leave it untouched.
            return core

        # Don't double-apply if a TOP already exists right after SELECT.
        head_end = m.end()
        if re.match(r"\s+TOP\s*\(", core[head_end:], flags=re.IGNORECASE):
            return core

        leading_ws, select_kw, distinct = m.group(1), m.group(2), m.group(3) or ""
        return f"{leading_ws}{select_kw}{distinct} TOP ({n_int}){core[head_end:]}"

    # ---- aggregates / casts ----
    def bigint_count(self) -> str:
        return "COUNT_BIG(*)"

    def cast_numeric(self, expr: str) -> str:
        # NUMERIC == DECIMAL in T-SQL.
        return f"CAST({expr} AS NUMERIC(38, 6))"

    # ---- identifiers / operators ----
    def quote_ident(self, ident: str) -> str:
        return "[" + ident.replace("]", "]]") + "]"

    def ilike(self, column: str, pattern_param: str) -> str:
        # SQL Server LIKE is case-insensitive under default CI collations.
        # If a case-sensitive collation is configured, callers should
        # apply LOWER() on both sides at the SQL-generation layer.
        return f"{column} LIKE {pattern_param}"

    # ---- runtime helpers ----
    def now(self) -> str:
        return "SYSUTCDATETIME()"

    def nulls_last(self, direction: str = "DESC") -> str:
        # SQL Server lacks NULLS LAST. Caller must add a CASE expression
        # to ORDER BY to emulate it. We return only the direction token
        # so generated SQL stays valid.
        d = (direction or "DESC").upper()
        return d

    def set_statement_timeout(self, ms: int) -> Optional[str]:
        # SQL Server has no exact equivalent. LOCK_TIMEOUT only covers
        # blocking waits; a true query timeout is configured client-side
        # (e.g., on the connection / cursor). Return None to signal
        # "no inline statement to issue".
        return None
