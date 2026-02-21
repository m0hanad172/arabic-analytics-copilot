"""
SQL Guardrails for Arabic Analytics Copilot

Goal:
- Keep /query debug_sql safe (read-only, single-statement, limited scope)
- Provide clear 400 errors instead of 500s

Drop-in usage (FastAPI):
    from app.core.sql_guardrails import guard_sql_or_raise

    sql = guard_sql_or_raise(sql, max_rows=req.max_rows, allowed_schemas={"bi"})
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Iterable, Set


# Conservative deny-lists
_DENY_KEYWORDS = {
    "insert", "update", "delete", "merge",
    "drop", "alter", "create", "truncate",
    "grant", "revoke",
    "vacuum", "analyze",  # ANALYZE executes when used as command; we allow EXPLAIN (without ANALYZE)
    "copy", "call", "execute", "do",
    "set", "reset", "show", "listen", "notify",
    "lock",
}

_DENY_FUNCTIONS = {
    "pg_sleep",
    "pg_read_file",
    "pg_write_file",
    "pg_ls_dir",
    "lo_import",
    "lo_export",
    "dblink",
}

# Schemas you almost never want exposed
_DENY_SCHEMAS = {"pg_catalog", "information_schema", "pg_toast"}


@dataclass(frozen=True)
class GuardrailsConfig:
    allowed_schemas: Set[str]
    max_rows_hard_cap: int = 5000
    allow_explain: bool = True
    deny_comments: bool = True


def _parse_allowed_schemas_from_env(default: str = "bi") -> Set[str]:
    raw = os.getenv("SQL_ALLOWED_SCHEMAS", default)
    items = [x.strip() for x in raw.split(",") if x.strip()]
    return set(items) if items else {"bi"}


def _count_semicolons_outside_quotes(sql: str) -> int:
    """
    Counts semicolons not inside single-quoted string literals.
    Handles doubled single quotes ('') used for escaping.
    """
    in_single = False
    i = 0
    count = 0
    while i < len(sql):
        ch = sql[i]
        if ch == "'":
            if in_single:
                # If next is also ', it's an escaped quote inside literal
                if i + 1 < len(sql) and sql[i + 1] == "'":
                    i += 2
                    continue
                in_single = False
            else:
                in_single = True
            i += 1
            continue
        if not in_single and ch == ";":
            count += 1
        i += 1
    return count


def _has_trailing_single_semicolon(sql: str) -> bool:
    """
    True if the only semicolon is a trailing statement terminator.
    """
    stripped = sql.rstrip()
    return stripped.endswith(";") and _count_semicolons_outside_quotes(sql) == 1


def _normalize_for_scan(sql: str) -> str:
    # Lowercase + collapse whitespace (we do NOT remove quotes; scanning is conservative)
    s = sql.strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s


def _starts_with_allowed_prefix(sql_norm: str, allow_explain: bool) -> bool:
    if sql_norm.startswith("select ") or sql_norm.startswith("with "):
        return True
    if allow_explain and sql_norm.startswith("explain "):
        # Disallow "explain analyze" because it executes the query
        if re.match(r"^explain\s+analyze\b", sql_norm):
            return False
        return True
    return False


def _reject_if_contains_comments(sql: str) -> None:
    # Very conservative: forbid SQL comments in debug_sql to prevent hiding payloads.
    if "--" in sql or "/*" in sql or "*/" in sql:
        raise ValueError("SQL comments are not allowed.")


def _reject_if_contains_denied_keywords(sql_norm: str) -> None:
    # Token scan: word boundary keywords
    for kw in _DENY_KEYWORDS:
        if re.search(rf"\b{re.escape(kw)}\b", sql_norm):
            raise ValueError(f"Disallowed keyword in SQL: {kw}")


def _reject_if_contains_denied_functions(sql_norm: str) -> None:
    for fn in _DENY_FUNCTIONS:
        if re.search(rf"\b{re.escape(fn)}\s*\(", sql_norm):
            raise ValueError(f"Disallowed function in SQL: {fn}()")


def _reject_if_contains_denied_schemas(sql_norm: str) -> None:
    for sch in _DENY_SCHEMAS:
        if re.search(rf"\b{re.escape(sch)}\s*\.", sql_norm):
            raise ValueError(f"Disallowed schema reference: {sch}.")


def _extract_schemas_from_from_join(sql_norm: str) -> Set[str]:
    """
    Extract schema names used in relation references inside the main FROM/JOIN section.

    IMPORTANT:
    - Avoid false positives from functions that use the keyword "from" inside parentheses
      (e.g., extract(year from f.order_date_d), substring(... from ...), trim(... from ...)).
    - We therefore only scan at top-level (paren_depth==0) and only *after* the main FROM
      keyword until a clause boundary (WHERE/GROUP/HAVING/ORDER/LIMIT/UNION...).
    """
    schemas: Set[str] = set()

    in_quote = False
    paren_depth = 0
    in_from = False

    i = 0
    n = len(sql_norm)

    def _is_ident_start(ch: str) -> bool:
        return ch.isalpha() or ch == "_"

    def _is_ident_char(ch: str) -> bool:
        return ch.isalnum() or ch == "_"

    while i < n:
        ch = sql_norm[i]

        # Handle single-quoted strings, including escaped ''
        if ch == "'":
            if in_quote and i + 1 < n and sql_norm[i + 1] == "'":
                i += 2
                continue
            in_quote = not in_quote
            i += 1
            continue

        if in_quote:
            i += 1
            continue

        # Track parentheses depth (ignore anything inside)
        if ch == "(":
            paren_depth += 1
            i += 1
            continue
        if ch == ")":
            paren_depth = max(paren_depth - 1, 0)
            i += 1
            continue

        if paren_depth != 0:
            i += 1
            continue

        # Top-level identifiers / keywords
        if _is_ident_start(ch):
            j = i + 1
            while j < n and _is_ident_char(sql_norm[j]):
                j += 1
            word = sql_norm[i:j]

            if word == "from":
                in_from = True
            elif word in {"where", "group", "having", "order", "limit", "union", "intersect", "except"}:
                # Clause boundary ends FROM/JOIN scanning
                in_from = False
            elif in_from:
                # If we see <schema>.<table> (schema qualified) in FROM/JOIN area, record schema
                k = j
                while k < n and sql_norm[k] == " ":
                    k += 1
                if k < n and sql_norm[k] == ".":
                    schemas.add(word)

            i = j
            continue

        i += 1

    return schemas


def _enforce_limit_if_missing(sql: str, max_rows: int) -> str:
    """
    If the SQL doesn't contain a LIMIT at all, append one.
    This is intentionally simple (no heavy parsing).
    """
    if re.search(r"\blimit\b", _normalize_for_scan(sql)):
        return sql
    # Remove trailing semicolon before appending
    core = sql.strip()
    if core.endswith(";"):
        core = core[:-1].rstrip()
    return f"{core} LIMIT {max_rows};"


def guard_sql_or_raise(
    sql: str,
    *,
    max_rows: int = 200,
    allowed_schemas: Set[str] | None = None,
    allow_explain: bool | None = None,
) -> str:
    """
    Validate debug_sql and return a safe SQL string (may append LIMIT).
    Raises ValueError with a clear message if blocked.
    """
    if not isinstance(sql, str) or not sql.strip():
        raise ValueError("Empty SQL.")

    cfg = GuardrailsConfig(
        allowed_schemas=allowed_schemas or _parse_allowed_schemas_from_env(),
        allow_explain=(allow_explain if allow_explain is not None else True),
    )

    # Hard cap max_rows
    try:
        max_rows_i = int(max_rows)
    except Exception:
        max_rows_i = 200
    if max_rows_i < 1:
        max_rows_i = 1
    if max_rows_i > cfg.max_rows_hard_cap:
        max_rows_i = cfg.max_rows_hard_cap

    # Single statement only (allow trailing ;)
    semi_count = _count_semicolons_outside_quotes(sql)
    if semi_count > 1:
        raise ValueError("Multiple SQL statements are not allowed.")
    if semi_count == 1 and not _has_trailing_single_semicolon(sql):
        raise ValueError("Semicolon is only allowed as a trailing terminator.")

    if cfg.deny_comments:
        _reject_if_contains_comments(sql)

    sql_norm = _normalize_for_scan(sql)

    if not _starts_with_allowed_prefix(sql_norm, cfg.allow_explain):
        raise ValueError("Only SELECT/WITH queries are allowed (optionally EXPLAIN).")

    _reject_if_contains_denied_keywords(sql_norm)
    _reject_if_contains_denied_functions(sql_norm)
    _reject_if_contains_denied_schemas(sql_norm)

    # Allowed schemas check (only for actual table refs in FROM/JOIN)
    used_schemas = _extract_schemas_from_from_join(sql_norm)
    for sch in used_schemas:
        if sch not in cfg.allowed_schemas:
            raise ValueError(f"Schema not allowed: {sch}.")

    # Ensure LIMIT exists (or append one)
    return _enforce_limit_if_missing(sql, max_rows_i)
