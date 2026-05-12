"""Probe SQL Server connectivity from Python (Phase C4).

Walks through likely (driver, server) combinations and prints the first
one that succeeds, along with the exact pyodbc connection string the
loader scripts should use. Never prints passwords (only Windows trusted
auth is supported here).

Usage::

    python scripts/test_sqlserver_connection.py
    python scripts/test_sqlserver_connection.py --database ArabicAnalytics
    MSSQL_SERVER=".\\SQLEXPRESS" python scripts/test_sqlserver_connection.py

Exit status is ``0`` when a working combination is found, ``1`` when
none do.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Optional


# Allow `python scripts/test_sqlserver_connection.py` from a repo
# checkout without installing the package.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.db.sqlserver_connect import (  # noqa: E402
    PREFERRED_DRIVERS,
    build_connection_string,
    default_server_candidates,
    iter_connection_candidates,
    list_available_drivers,
    resolve_database_from_env,
    resolve_server_from_env,
)


def _print(msg: str) -> None:
    print(msg, flush=True)


def _try_connect(conn_str: str, timeout: int) -> Optional[str]:
    """Attempt a single connection. Returns ``None`` on success, or a
    short error string. Imports pyodbc lazily so the helper module
    stays importable when pyodbc is not installed."""
    try:
        import pyodbc  # type: ignore
    except Exception as e:
        return f"pyodbc unavailable: {type(e).__name__}: {e}"
    try:
        with pyodbc.connect(conn_str, timeout=timeout) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1;")
                cur.fetchone()
        return None
    except Exception as e:
        return f"{type(e).__name__}: {e}"


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database", default=resolve_database_from_env(),
        help="Target database name (default: ArabicAnalytics or MSSQL_DATABASE env).",
    )
    parser.add_argument(
        "--server", default=resolve_server_from_env(),
        help="Override SERVER= (e.g. '.\\SQLEXPRESS'). When omitted, tries the full candidate list.",
    )
    parser.add_argument(
        "--timeout", type=int, default=5,
        help="Per-attempt login timeout in seconds (default: 5).",
    )
    parser.add_argument(
        "--first-only", action="store_true",
        help="Stop after the first successful connection (default behaviour).",
    )
    args = parser.parse_args(argv)

    _print("=== SQL Server connection probe ===")
    available = list_available_drivers()
    _print(f"Installed ODBC drivers ({len(available)}):")
    for d in available:
        marker = "*" if d in PREFERRED_DRIVERS else " "
        _print(f"  {marker} {d}")
    _print("")

    # Restrict to drivers the local box actually has.
    drivers = [d for d in PREFERRED_DRIVERS if d in set(available)]
    if not drivers:
        _print("ERROR: none of the preferred ODBC drivers are installed.")
        _print(f"Preferred drivers: {', '.join(PREFERRED_DRIVERS)}")
        return 1

    servers = [args.server] if args.server else default_server_candidates()

    _print(f"Database: {args.database}")
    _print(f"Servers to try ({len(servers)}):")
    for s in servers:
        _print(f"  - {s}")
    _print("")

    successes = []
    for attempt in iter_connection_candidates(drivers=drivers, servers=servers):
        conn_str = build_connection_string(
            attempt.driver, attempt.server,
            database=args.database, trusted=True,
            trust_server_cert=True, encrypt=False,
        )
        _print(f"--> Trying driver={attempt.driver!r}  server={attempt.server!r}")
        err = _try_connect(conn_str, timeout=args.timeout)
        if err is None:
            _print("    SUCCESS")
            _print(f"    Connection string: {conn_str}")
            successes.append((attempt, conn_str))
            if args.first_only or True:  # first hit is good enough
                break
        else:
            _print(f"    failed: {err}")

    _print("")
    if not successes:
        _print("No working (driver, server) combination found.")
        _print("Troubleshooting checklist:")
        _print("  1. SQL Server Configuration Manager > Network Configuration")
        _print("     > Protocols for SQLEXPRESS: enable TCP/IP and Shared Memory.")
        _print("  2. SQL Server Services: restart SQL Server (SQLEXPRESS).")
        _print("  3. Start the 'SQL Server Browser' service so named")
        _print("     instances resolve over UDP/1434.")
        _print("  4. For Driver 18, keep TrustServerCertificate=yes and Encrypt=no")
        _print("     on a local dev box without a signed certificate.")
        return 1

    attempt, conn_str = successes[0]
    _print("=== USE THIS ===")
    _print(f"DRIVER={attempt.driver!r}")
    _print(f"SERVER={attempt.server!r}")
    _print(f"Connection string: {conn_str}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
