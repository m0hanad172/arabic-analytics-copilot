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
def _current_windows_host() -> Optional[str]:
    return (
        os.environ.get("COMPUTERNAME")
        or os.environ.get("HOSTNAME")
        or None
    )


def _sqlserver_original_machine_names() -> Tuple[str, ...]:
    """Return SQL Server's recorded machine names from the registry.

    SQL Server named instances can keep the machine name that existed at
    install time even after Windows is renamed. SSMS may therefore show
    ``@@SERVERNAME`` that differs from ``COMPUTERNAME``.
    """
    try:
        import winreg  # type: ignore[attr-defined]
    except Exception:
        return ()

    root_path = r"SOFTWARE\Microsoft\Microsoft SQL Server"
    names: List[str] = []
    try:
        root = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, root_path)
    except OSError:
        return ()

    try:
        index = 0
        while True:
            try:
                subkey = winreg.EnumKey(root, index)
            except OSError:
                break
            index += 1
            try:
                machines = winreg.OpenKey(root, rf"{subkey}\Machines")
                value, _value_type = winreg.QueryValueEx(machines, "OriginalMachineName")
                if value:
                    names.append(str(value))
            except OSError:
                continue
    finally:
        winreg.CloseKey(root)

    return _dedupe_preserve_order(names)


def _dedupe_preserve_order(items: Sequence[str]) -> Tuple[str, ...]:
    seen = set()
    out: List[str] = []
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return tuple(out)


def default_server_candidates(host: Optional[str] = None, instance: str = "SQLEXPRESS") -> Tuple[str, ...]:
    """Return ordered list of SERVER= strings to try.

    Tweaking host/instance keeps this useful for future deployments
    without baking the developer machine name into tests. When ``host``
    is omitted, the current Windows ``COMPUTERNAME`` is used.
    """
    hosts = [host] if host else [
        _current_windows_host(),
        *_sqlserver_original_machine_names(),
    ]
    candidates = [
        rf".\{instance}",
    ]
    for h in hosts:
        if h:
            candidates.append(rf"{h}\{instance}")
    candidates.extend([
        rf"localhost\{instance}",
        rf"(local)\{instance}",
        rf"lpc:.\{instance}",
        rf"np:\\.\pipe\MSSQL${instance}\sql\query",
        r"tcp:localhost,1433",
        r"tcp:127.0.0.1,1433",
    ])
    return _dedupe_preserve_order(candidates)


def default_named_instance_server(instance: str = "SQLEXPRESS") -> str:
    """Best default named-instance server for local smoke scripts.

    Prefer SQL Server's original machine name when present because SSMS
    and ``@@SERVERNAME`` can retain it after Windows is renamed.
    """
    host = next(iter(_sqlserver_original_machine_names()), None) or _current_windows_host()
    return rf"{host}\{instance}" if host else rf".\{instance}"


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
    user: Optional[str] = None,
    password: Optional[str] = None,
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
    use_sql_auth = bool(user and password)
    if use_sql_auth:
        parts.append(f"UID={user}")
        parts.append(f"PWD={password}")
    elif trusted:
        parts.append("Trusted_Connection=yes")
    if trust_server_cert:
        parts.append("TrustServerCertificate=yes")
    if encrypt is not None:
        parts.append("Encrypt=" + ("yes" if encrypt else "no"))
    # Single trailing ;.
    return ";".join(parts) + ";"


def mask_password(conn_str: str) -> str:
    """Mask password-like key/value pairs in an ODBC connection string."""
    return re.sub(
        r"(?i)(^|;)\s*(PWD|Password)\s*=\s*[^;]*",
        lambda m: f"{m.group(1)}{m.group(2)}=***",
        conn_str or "",
    )


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


def resolve_sql_auth_from_env() -> Tuple[Optional[str], Optional[str]]:
    """Return SQL auth credentials only when both env vars are set."""
    user = os.environ.get("MSSQL_USER")
    password = os.environ.get("MSSQL_PASSWORD")
    if user and password:
        return user, password
    return None, None


__all__ = [
    "PREFERRED_DRIVERS",
    "ConnectionAttempt",
    "build_connection_string",
    "build_drop_if_exists",
    "build_staging_create_table",
    "default_named_instance_server",
    "default_server_candidates",
    "iter_connection_candidates",
    "list_available_drivers",
    "mask_password",
    "pick_available_driver",
    "resolve_database_from_env",
    "resolve_driver_from_env",
    "resolve_server_from_env",
    "resolve_sql_auth_from_env",
    "sanitize_column_name",
]
