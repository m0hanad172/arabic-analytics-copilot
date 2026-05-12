"""PostgreSQL dialect.

Emits exactly the SQL fragments the project produces today so that
turning on the dialect layer is a no-op for the working backend.
"""
from __future__ import annotations

import re
from typing import Optional

from backend.app.db.dialects.base import SqlDialect


class PostgresDialect(SqlDialect):
    name = "postgres"

    # ---- LIMIT / TOP ----
    def limit_clause(self, n: int) -> str:
        return f"LIMIT {int(n)}"

    def apply_limit(self, sql: str, n: int) -> str:
        # Mirror today's templates: LIMIT goes on its own line at the end.
        # If the SQL already ends with a LIMIT clause, leave it as-is.
        core = sql.rstrip().rstrip(";").rstrip()
        if re.search(r"\blimit\s+\d+\s*$", core, flags=re.IGNORECASE):
            return core
        return f"{core}\n{self.limit_clause(n)}"

    # ---- aggregates / casts ----
    def bigint_count(self) -> str:
        return "COUNT(*)::bigint"

    def cast_numeric(self, expr: str) -> str:
        return f"{expr}::numeric"

    # ---- identifiers / operators ----
    def quote_ident(self, ident: str) -> str:
        return '"' + ident.replace('"', '""') + '"'

    def ilike(self, column: str, pattern_param: str) -> str:
        return f"{column} ILIKE {pattern_param}"

    # ---- runtime helpers ----
    def now(self) -> str:
        return "now()"

    def nulls_last(self, direction: str = "DESC") -> str:
        d = (direction or "DESC").upper()
        return f"{d} NULLS LAST"

    def set_statement_timeout(self, ms: int) -> Optional[str]:
        return f"SET statement_timeout = {int(ms)}"
