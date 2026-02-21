import re
import sqlparse

DISALLOWED = {
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "GRANT", "REVOKE", "TRUNCATE",
    "COPY", "CALL", "DO", "EXECUTE"
}

def _contains_disallowed_keywords(sql: str) -> bool:
    upper = sql.upper()
    return any(re.search(rf"\b{k}\b", upper) for k in DISALLOWED)

def assert_safe_select(sql: str) -> None:
    if not sql or not sql.strip():
        raise ValueError("Empty SQL")

    # No multi-statement
    if ";" in sql.strip().rstrip(";"):
        raise ValueError("Multiple statements are not allowed")

    if _contains_disallowed_keywords(sql):
        raise ValueError("Disallowed keyword detected")

    parsed = sqlparse.parse(sql)
    if not parsed:
        raise ValueError("Invalid SQL")

    stmt = parsed[0]
    first = next((t for t in stmt.tokens if not t.is_whitespace), None)
    if first is None:
        raise ValueError("Invalid SQL")

    first_kw = first.normalized.upper()
    if first_kw not in ("SELECT", "WITH"):
        raise ValueError("Only SELECT/WITH queries are allowed")

def assert_only_allowed_schema(sql: str, allowed_schema: str) -> None:
    # Basic allowlist: only allow references starting with allowed_schema.
    # This is intentionally strict for safety in Phase 2.
    upper = sql.upper()
    # Reject explicit other schemas like public., information_schema., pg_catalog.
    bad = re.findall(r"\b([A-Z_][A-Z0-9_]*)\s*\.", upper)
    bad = {b.lower() for b in bad}

    if bad and (bad != {allowed_schema.lower()}):
        raise ValueError(f"Only schema '{allowed_schema}' is allowed (found: {sorted(bad)})")
