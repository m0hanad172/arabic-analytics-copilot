"""SQL Server connection helpers (Phase C4 hotfix).

Pure, dependency-light module so unit tests can exercise the
connection-string builder and the staging-table generator without a
live SQL Server (or even ``pyodbc``) installed.

Used by:
    scripts/test_sqlserver_connection.py
    scripts/load_sqlserver_staging.py
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, Tuple


# ---------------------------------------------------------------------------
# Drivers + servers (ordered by preference)
# ---------------------------------------------------------------------------
# Newest first — pyodbc will simply fail to connect for drivers not
# installed locally, so the test script can skip them gracefully.
PREFERRED_DRIVERS: Tuple[str, ...] = (
    "ODBC Driver 18 for SQL Server",
    "ODBC Driver 17 for SQL Server",
    "SQL Server Native Client 11.0",
    "SQL Server",
)

# Variations covering Windows named-instance / shared-memory / pipe /
# TCP fallbacks. Tried in this order: cheap/local first, TCP last.
def default_server_candidates(host: str = "MOHANADLENOVO", instance: str = "SQLEXPRESS") -> Tuple[str, ...]:
    """Return ordered list of SERVER= strings to try.

    Tweaking host/instance keeps this useful for future deployments
    without baking the developer machine name into tests.
    """
    return (
        rf".\{instance}",
        rf"localhost\{instance}",
        rf"(local)\{instance}",
        rf"{host}\{instance}",
        rf"lpc:.\{instance}",
        rf"np:\\.\pipe\MSSQL${instance}\sql\query",
        r"tcp:localhost,1433",
        r"tcp:127.0.0.1,1433",
    )


# ---------------------------------------------------------------------------
# Connection-string builder
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ConnectionAttempt:
    driver: str
    server: str

    def odbc_keys(self) -> List[str]:
        """The ODBC key=value parts, ordered. Used by build_connection_string."""
        return [
            f"DRIVER={{{self.driver}}}",
            f"SERVER={self.server}",
        ]


def build_connection_string(
    driver: str,
    server: str,
    database: str = "ArabicAnalytics",
    *,
    trusted: bool = True,
    trust_server_cert: bool = True,
    encrypt: Optional[bool] = None,
) -> str:
    """Build an ODBC connection string for SQL Server.

    Windows trusted auth only — this project does not use SQL logins.
    No secrets are ever interpolated; the returned string is safe to
    print or log.

    Args:
        driver: ODBC driver display name (one of PREFERRED_DRIVERS).
        server: SERVER= value, e.g. ".\\SQLEXPRESS" or "tcp:localhost,1433".
        database: database name; defaults to ArabicAnalytics.
        trusted: emit Trusted_Connection=yes (Windows auth).
        trust_server_cert: emit TrustServerCertificate=yes (needed for
            Driver 18 against a local box with no signed cert).
        encrypt: if not None, append Encrypt=yes/no. For Driver 18 set
            False on a local dev box to skip TLS entirely.

    Returns:
        Semicolon-terminated connection string without trailing
        whitespace.
    """
    parts: List[str] = [
        f"DRIVER={{{driver}}}",
        f"SERVER={server}",
        f"DATABASE={database}",
    ]
    if trusted:
        parts.append("Trusted_Connection=yes")
    if trust_server_cert:
        parts.append("TrustServerCertificate=yes")
    if encrypt is not None:
        parts.append("Encrypt=" + ("yes" if encrypt else "no"))
    # Single trailing ;.
    return ";".join(parts) + ";"


def iter_connection_candidates(
    drivers: Sequence[str] = PREFERRED_DRIVERS,
    servers: Optional[Sequence[str]] = None,
) -> Iterable[ConnectionAttempt]:
    """Yield (driver, server) attempts in priority order.

    Outer loop is *server* (cheap local pipes first), inner is *driver*
    so we exhaust drivers for the most likely server before trying a
    less-likely one — fast feedback when the right server pattern works.
    """
    if servers is None:
        servers = default_server_candidates()
    for s in servers:
        for d in drivers:
            yield ConnectionAttempt(driver=d, server=s)


# ---------------------------------------------------------------------------
# Driver discovery
# ---------------------------------------------------------------------------
def list_available_drivers() -> List[str]:
    """Return the ODBC driver display names visible to pyodbc.

    Returns an empty list (rather than raising) when pyodbc is not
    installed, so the test script can still produce a useful error.
    """
    try:
        import pyodbc  # type: ignore
    except Exception:
        return []
    try:
        return list(pyodbc.drivers())
    except Exception:
        return []


def pick_available_driver(
    available: Sequence[str],
    preferred: Sequence[str] = PREFERRED_DRIVERS,
) -> Optional[str]:
    """Return the highest-priority driver that is installed locally."""
    avail_set = {d.strip() for d in available}
    for d in preferred:
        if d in avail_set:
            return d
    return None


# ---------------------------------------------------------------------------
# CSV column sanitisation + staging DDL
# ---------------------------------------------------------------------------
_SAFE_IDENT = re.compile(r"[^0-9A-Za-z_]+")


def sanitize_column_name(name: str) -> str:
    """Make a CSV header safe to use as a SQL Server column name.

    - Replace any run of non-alphanumeric/underscore characters with ``_``.
    - Strip leading/trailing underscores.
    - Prefix ``col_`` if the result is empty or starts with a digit.
    """
    if name is None:
        name = ""
    cleaned = _SAFE_IDENT.sub("_", str(name)).strip("_")
    if not cleaned:
        return "col_unnamed"
    if cleaned[0].isdigit():
        return f"col_{cleaned}"
    return cleaned


def build_staging_create_table(
    table: str,
    columns: Sequence[str],
    *,
    column_type: str = "NVARCHAR(400)",
    nullable: bool = True,
) -> str:
    """Generate a CREATE TABLE statement for a staging load.

    The table is created with every CSV column as the same wide
    nullable string type by default so SSMS / fast_executemany never
    rejects a row for codepage or numeric-precision reasons. A second
    pass (Phase C4) will cast and copy into ``bi.fact_sales_line``.
    """
    null_kw = "NULL" if nullable else "NOT NULL"
    cols_sql = ",\n    ".join(
        f"[{sanitize_column_name(c)}] {column_type} {null_kw}" for c in columns
    )
    return f"CREATE TABLE {table} (\n    {cols_sql}\n);"


def build_drop_if_exists(table: str) -> str:
    """Return an idempotent DROP TABLE statement."""
    return f"IF OBJECT_ID(N'{table}', N'U') IS NOT NULL DROP TABLE {table};"


# ---------------------------------------------------------------------------
# Env overrides
# ---------------------------------------------------------------------------
def resolve_server_from_env(default: Optional[str] = None) -> Optional[str]:
    """Return ``MSSQL_SERVER`` env value or ``default``."""
    return os.environ.get("MSSQL_SERVER") or default


def resolve_driver_from_env(default: Optional[str] = None) -> Optional[str]:
    """Return ``MSSQL_DRIVER`` env value or ``default``."""
    return os.environ.get("MSSQL_DRIVER") or default


def resolve_database_from_env(default: str = "ArabicAnalytics") -> str:
    return os.environ.get("MSSQL_DATABASE") or default


__all__ = [
    "PREFERRED_DRIVERS",
    "ConnectionAttempt",
    "build_connection_string",
    "build_drop_if_exists",
    "build_staging_create_table",
    "default_server_candidates",
    "iter_connection_candidates",
    "list_available_drivers",
    "pick_available_driver",
    "resolve_database_from_env",
    "resolve_driver_from_env",
    "resolve_server_from_env",
    "sanitize_column_name",
]
