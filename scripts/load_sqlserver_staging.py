"""Load data/clean/bi_ready_clean.csv into dbo.bi_ready_clean (Phase C4).

Staging-only loader: every column lands as NVARCHAR(400) NULL so the
SQL Server destination never rejects a row for codepage / precision /
nullability reasons. A follow-up step (Phase C4 next) casts and copies
into bi.fact_sales_line via an INSERT ... SELECT.

Usage::

    python scripts/load_sqlserver_staging.py
    python scripts/load_sqlserver_staging.py --csv data/clean/bi_ready_clean.csv
    MSSQL_SERVER=".\\SQLEXPRESS" python scripts/load_sqlserver_staging.py

Environment overrides:
    MSSQL_SERVER     SERVER= value (e.g. ".\\SQLEXPRESS")
    MSSQL_DRIVER     ODBC driver display name
    MSSQL_DATABASE   target database (default: ArabicAnalytics)

The script uses Windows trusted authentication only — no passwords are
ever read or printed.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Optional


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.db.sqlserver_connect import (  # noqa: E402
    PREFERRED_DRIVERS,
    build_connection_string,
    build_drop_if_exists,
    build_staging_create_table,
    list_available_drivers,
    mask_password,
    pick_available_driver,
    resolve_database_from_env,
    resolve_driver_from_env,
    resolve_server_from_env,
    resolve_sql_auth_from_env,
    sanitize_column_name,
)


DEFAULT_CSV = ROOT / "data" / "clean" / "bi_ready_clean.csv"
DEFAULT_STAGING = "dbo.bi_ready_clean"


def _print(msg: str) -> None:
    print(msg, flush=True)


def _require_pyodbc():
    try:
        import pyodbc  # type: ignore
    except Exception as e:
        raise SystemExit(f"pyodbc is required: {e}") from e
    return pyodbc


def _require_pandas():
    try:
        import pandas as pd  # type: ignore
    except Exception as e:
        raise SystemExit(f"pandas is required: {e}") from e
    return pd


def _resolve_driver_and_server(args) -> tuple[str, str]:
    driver = args.driver or resolve_driver_from_env()
    if not driver:
        driver = pick_available_driver(list_available_drivers(), PREFERRED_DRIVERS)
    if not driver:
        raise SystemExit(
            "No suitable ODBC driver installed. Tried: "
            + ", ".join(PREFERRED_DRIVERS)
        )

    server = args.server or resolve_server_from_env()
    if not server:
        raise SystemExit(
            "SERVER not provided. Set --server, or MSSQL_SERVER env, or run "
            "scripts/test_sqlserver_connection.py to discover one."
        )
    return driver, server


def _load_csv_dataframe(csv_path: Path):
    pd = _require_pandas()
    if not csv_path.exists():
        raise SystemExit(f"CSV not found: {csv_path}")
    df = pd.read_csv(csv_path)
    # NaN -> None so pyodbc binds them as SQL NULL.
    df = df.where(pd.notnull(df), None)
    return df


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--csv", default=str(DEFAULT_CSV),
        help=f"Source CSV (default: {DEFAULT_CSV}).",
    )
    parser.add_argument(
        "--table", default=DEFAULT_STAGING,
        help=f"Destination staging table (default: {DEFAULT_STAGING}).",
    )
    parser.add_argument("--driver", default=None, help="ODBC driver display name.")
    parser.add_argument("--server", default=None, help="SERVER= value.")
    parser.add_argument(
        "--database", default=resolve_database_from_env(),
        help="Target database (default: ArabicAnalytics or MSSQL_DATABASE).",
    )
    parser.add_argument(
        "--batch-size", type=int, default=1000,
        help="fast_executemany batch size (default: 1000).",
    )
    parser.add_argument(
        "--encrypt", choices=("yes", "no"), default="no",
        help="Encrypt= setting (Driver 18 only; default: no for local dev).",
    )
    args = parser.parse_args(argv)

    driver, server = _resolve_driver_and_server(args)
    encrypt_flag = args.encrypt == "yes"
    sql_user, sql_password = resolve_sql_auth_from_env()
    conn_str = build_connection_string(
        driver, server,
        database=args.database, trusted=True,
        user=sql_user,
        password=sql_password,
        trust_server_cert=True, encrypt=encrypt_flag,
    )
    _print(f"Driver: {driver}")
    _print(f"Server: {server}")
    _print(f"Database: {args.database}")
    _print(f"Authentication: {'SQL auth' if sql_user and sql_password else 'Windows trusted'}")
    _print(f"Connection string: {mask_password(conn_str)}")

    df = _load_csv_dataframe(Path(args.csv))
    _print(f"CSV rows:    {len(df)}")
    _print(f"CSV columns: {len(df.columns)}")

    sanitized_cols = [sanitize_column_name(c) for c in df.columns]
    create_sql = build_staging_create_table(args.table, df.columns)
    drop_sql = build_drop_if_exists(args.table)

    col_list = ", ".join(f"[{c}]" for c in sanitized_cols)
    placeholders = ", ".join("?" for _ in sanitized_cols)
    insert_sql = (
        f"INSERT INTO {args.table} ({col_list})\nVALUES ({placeholders})"
    )

    pyodbc = _require_pyodbc()
    t0 = time.time()
    with pyodbc.connect(conn_str, autocommit=False) as conn:
        cur = conn.cursor()
        cur.execute(drop_sql)
        cur.execute(create_sql)
        conn.commit()

        cur.fast_executemany = True
        rows = df.astype(object).where(df.notna(), None).values.tolist()

        # Batched inserts so a partial failure does not blow the whole load.
        total = 0
        for i in range(0, len(rows), args.batch_size):
            chunk = rows[i : i + args.batch_size]
            cur.executemany(insert_sql, chunk)
            total += len(chunk)
            conn.commit()
            _print(f"  inserted {total}/{len(rows)}")

        cur.execute(f"SELECT COUNT(*) FROM {args.table};")
        loaded = cur.fetchone()[0]

    elapsed = time.time() - t0
    _print(f"Loaded {loaded} rows into {args.table} in {elapsed:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
