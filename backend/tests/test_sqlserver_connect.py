"""Unit tests for the SQL Server connection / staging helpers (Phase C4 hotfix).

No live SQL Server required.
"""
from __future__ import annotations

import importlib
import re
import sys
from pathlib import Path

import pytest

from backend.app.db import sqlserver_connect as ssc


# ---- Connection-string builder --------------------------------------------
def test_build_connection_string_includes_required_keys():
    s = ssc.build_connection_string(
        "ODBC Driver 18 for SQL Server", r".\SQLEXPRESS",
    )
    assert "DRIVER={ODBC Driver 18 for SQL Server}" in s
    assert r"SERVER=.\SQLEXPRESS" in s
    assert "DATABASE=ArabicAnalytics" in s
    assert "Trusted_Connection=yes" in s
    assert "TrustServerCertificate=yes" in s
    # Exactly one trailing semicolon.
    assert s.endswith(";")
    assert not s.endswith(";;")


def test_build_connection_string_emits_encrypt_when_requested():
    s = ssc.build_connection_string(
        "ODBC Driver 18 for SQL Server", r".\SQLEXPRESS", encrypt=False,
    )
    assert "Encrypt=no" in s
    s2 = ssc.build_connection_string(
        "ODBC Driver 18 for SQL Server", r".\SQLEXPRESS", encrypt=True,
    )
    assert "Encrypt=yes" in s2


def test_build_connection_string_defaults_to_windows_auth_without_password():
    s = ssc.build_connection_string(
        "ODBC Driver 18 for SQL Server", r".\SQLEXPRESS",
        database="ArabicAnalytics",
    )
    lowered = s.lower()
    for forbidden in ("pwd=", "password=", "uid=", "user id="):
        assert forbidden not in lowered, f"forbidden token {forbidden!r} in {s!r}"


def test_build_connection_string_supports_sql_auth_and_omits_trusted_connection():
    s = ssc.build_connection_string(
        "ODBC Driver 18 for SQL Server",
        r".\SQLEXPRESS",
        user="aac_app",
        password="secret",
        encrypt=False,
    )
    assert "UID=aac_app" in s
    assert "PWD=secret" in s
    assert "Trusted_Connection" not in s
    assert "Encrypt=no" in s


def test_mask_password_masks_pwd_values():
    s = (
        "DRIVER={ODBC Driver 18 for SQL Server};"
        r"SERVER=.\SQLEXPRESS;"
        "UID=aac_app;PWD=secret;Encrypt=no;"
    )
    masked = ssc.mask_password(s)
    assert "PWD=***" in masked
    assert "secret" not in masked
    assert "UID=aac_app" in masked


def test_build_connection_string_can_opt_out_of_trusted_connection():
    s = ssc.build_connection_string(
        "ODBC Driver 18 for SQL Server", r".\SQLEXPRESS", trusted=False,
    )
    assert "Trusted_Connection" not in s


# ---- Candidate iteration --------------------------------------------------
def test_default_server_candidates_contains_required_patterns():
    candidates = ssc.default_server_candidates(host="09154936")
    expected_present = {
        r".\SQLEXPRESS",
        r"09154936\SQLEXPRESS",
        r"localhost\SQLEXPRESS",
        r"(local)\SQLEXPRESS",
        r"lpc:.\SQLEXPRESS",
        r"np:\\.\pipe\MSSQL$SQLEXPRESS\sql\query",
        r"tcp:localhost,1433",
        r"tcp:127.0.0.1,1433",
    }
    assert expected_present.issubset(set(candidates))


def test_default_server_candidates_uses_computername(monkeypatch):
    monkeypatch.setenv("COMPUTERNAME", "09154936")
    monkeypatch.setattr(ssc, "_sqlserver_original_machine_names", lambda: ())
    candidates = ssc.default_server_candidates()
    assert candidates[:4] == (
        r".\SQLEXPRESS",
        r"09154936\SQLEXPRESS",
        r"localhost\SQLEXPRESS",
        r"(local)\SQLEXPRESS",
    )


def test_default_server_candidates_uses_sqlserver_original_machine_name(monkeypatch):
    monkeypatch.setenv("COMPUTERNAME", "RENAMEDBOX")
    monkeypatch.setattr(ssc, "_sqlserver_original_machine_names", lambda: ("09154936",))
    candidates = ssc.default_server_candidates()
    assert candidates[:5] == (
        r".\SQLEXPRESS",
        r"RENAMEDBOX\SQLEXPRESS",
        r"09154936\SQLEXPRESS",
        r"localhost\SQLEXPRESS",
        r"(local)\SQLEXPRESS",
    )


def test_default_named_instance_server_prefers_original_machine_name(monkeypatch):
    monkeypatch.setenv("COMPUTERNAME", "RENAMEDBOX")
    monkeypatch.setattr(ssc, "_sqlserver_original_machine_names", lambda: ("09154936",))
    assert ssc.default_named_instance_server() == r"09154936\SQLEXPRESS"


def test_default_server_candidates_orders_local_before_tcp():
    candidates = ssc.default_server_candidates()
    # Local pipes must come before TCP fallbacks.
    idx_local = candidates.index(r".\SQLEXPRESS")
    idx_tcp_localhost = candidates.index(r"tcp:localhost,1433")
    idx_tcp_loopback = candidates.index(r"tcp:127.0.0.1,1433")
    assert idx_local < idx_tcp_localhost < idx_tcp_loopback


def test_preferred_drivers_priority_order():
    # Driver 18 first (newest), then 17, then Native Client, then SQL Server.
    expected_order = (
        "ODBC Driver 18 for SQL Server",
        "ODBC Driver 17 for SQL Server",
        "SQL Server Native Client 11.0",
        "SQL Server",
    )
    assert ssc.PREFERRED_DRIVERS[:4] == expected_order


def test_iter_connection_candidates_emits_all_combinations():
    drivers = ("Driver A", "Driver B")
    servers = ("S1", "S2", "S3")
    combos = list(ssc.iter_connection_candidates(drivers=drivers, servers=servers))
    # 2 drivers x 3 servers = 6 attempts.
    assert len(combos) == 6
    # Outer loop is server, inner is driver.
    assert combos[0].server == "S1" and combos[0].driver == "Driver A"
    assert combos[1].server == "S1" and combos[1].driver == "Driver B"
    assert combos[2].server == "S2" and combos[2].driver == "Driver A"


def test_pick_available_driver_picks_highest_priority():
    # Driver 17 + Native Client installed; Driver 18 not -> picks 17.
    chosen = ssc.pick_available_driver(
        available=["SQL Server", "ODBC Driver 17 for SQL Server", "SQL Server Native Client 11.0"],
    )
    assert chosen == "ODBC Driver 17 for SQL Server"


def test_pick_available_driver_returns_none_when_nothing_matches():
    assert ssc.pick_available_driver(available=["Foo", "Bar"]) is None


# ---- Column name sanitisation ---------------------------------------------
@pytest.mark.parametrize("raw, expected", [
    ("order_no", "order_no"),
    ("Order Date", "Order_Date"),
    ("price (usd)", "price_usd"),
    ("  spaces  ", "spaces"),
    ("---", "col_unnamed"),
    ("", "col_unnamed"),
    ("1col", "col_1col"),
    ("q.discount.pct", "q_discount_pct"),
])
def test_sanitize_column_name(raw, expected):
    assert ssc.sanitize_column_name(raw) == expected


# ---- Staging CREATE TABLE -------------------------------------------------
def test_build_staging_create_table_generates_expected_ddl():
    ddl = ssc.build_staging_create_table(
        "dbo.bi_ready_clean",
        columns=["order_no", "Order Date", "price (usd)"],
    )
    assert ddl.startswith("CREATE TABLE dbo.bi_ready_clean (")
    assert ddl.rstrip().endswith(");")
    # Every column wrapped in brackets and typed NVARCHAR(400) NULL.
    assert "[order_no] NVARCHAR(400) NULL" in ddl
    assert "[Order_Date] NVARCHAR(400) NULL" in ddl
    assert "[price_usd] NVARCHAR(400) NULL" in ddl


def test_build_staging_create_table_supports_not_null_override():
    ddl = ssc.build_staging_create_table(
        "dbo.t", columns=["c"], nullable=False,
    )
    assert "[c] NVARCHAR(400) NOT NULL" in ddl


def test_build_drop_if_exists():
    ddl = ssc.build_drop_if_exists("dbo.bi_ready_clean")
    assert ddl == "IF OBJECT_ID(N'dbo.bi_ready_clean', N'U') IS NOT NULL DROP TABLE dbo.bi_ready_clean;"


# ---- Env resolvers --------------------------------------------------------
def test_env_resolvers_honor_environment(monkeypatch):
    monkeypatch.setenv("MSSQL_SERVER", r".\SQLEXPRESS")
    monkeypatch.setenv("MSSQL_DRIVER", "ODBC Driver 17 for SQL Server")
    monkeypatch.setenv("MSSQL_DATABASE", "OtherDb")
    monkeypatch.setenv("MSSQL_USER", "aac_app")
    monkeypatch.setenv("MSSQL_PASSWORD", "secret")
    assert ssc.resolve_server_from_env() == r".\SQLEXPRESS"
    assert ssc.resolve_driver_from_env() == "ODBC Driver 17 for SQL Server"
    assert ssc.resolve_database_from_env() == "OtherDb"
    assert ssc.resolve_sql_auth_from_env() == ("aac_app", "secret")


def test_env_resolvers_fall_back_to_defaults(monkeypatch):
    monkeypatch.delenv("MSSQL_SERVER", raising=False)
    monkeypatch.delenv("MSSQL_DRIVER", raising=False)
    monkeypatch.delenv("MSSQL_DATABASE", raising=False)
    monkeypatch.delenv("MSSQL_USER", raising=False)
    monkeypatch.delenv("MSSQL_PASSWORD", raising=False)
    assert ssc.resolve_server_from_env(default="fallback") == "fallback"
    assert ssc.resolve_driver_from_env(default=None) is None
    assert ssc.resolve_database_from_env() == "ArabicAnalytics"
    assert ssc.resolve_sql_auth_from_env() == (None, None)


def test_sql_auth_env_requires_user_and_password(monkeypatch):
    monkeypatch.setenv("MSSQL_USER", "aac_app")
    monkeypatch.delenv("MSSQL_PASSWORD", raising=False)
    assert ssc.resolve_sql_auth_from_env() == (None, None)


# ---- Script importability -------------------------------------------------
SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"


def _import_script_module(module_name: str, file_name: str):
    """Importlib helper: load a top-level script as a module without
    requiring scripts/ to be a package."""
    import importlib.util

    path = SCRIPTS_DIR / file_name
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_test_sqlserver_connection_script_imports_cleanly():
    mod = _import_script_module(
        "test_sqlserver_connection", "test_sqlserver_connection.py",
    )
    assert hasattr(mod, "main")


def test_load_sqlserver_staging_script_imports_cleanly():
    mod = _import_script_module(
        "load_sqlserver_staging", "load_sqlserver_staging.py",
    )
    assert hasattr(mod, "main")
    assert mod.DEFAULT_STAGING == "dbo.bi_ready_clean"


# ---- Tracked configuration docs ------------------------------------------
def test_env_example_documents_sqlserver_auth_without_real_passwords():
    env_example = Path(__file__).resolve().parents[1] / ".env.example"
    text = env_example.read_text(encoding="utf-8")

    assert "DATABASE_BACKEND=postgres" in text
    assert "COMPILER_BACKEND=db" in text
    assert "odbc_connect=" in text
    assert "Trusted_Connection%3Dyes" in text
    assert "UID%3D%3Csql_login%3E" in text
    assert "PWD%3D%3Csql_password%3E" in text
    assert "MSSQL_PASSWORD=<sql_password>" in text
    assert "DB_PASSWORD=<postgres_password>" in text
    assert "mssql+aioodbc://@." not in text
    assert "mssql+pyodbc://@." not in text


def test_sqlserver_migration_plan_uses_odbc_connect_examples():
    plan = Path(__file__).resolve().parents[2] / "docs" / "SQLSERVER_MIGRATION_PLAN.md"
    text = plan.read_text(encoding="utf-8")

    assert "odbc_connect=" in text
    assert "Trusted_Connection%3Dyes" in text
    assert "UID%3D%3Csql_login%3E" in text
    assert "PWD%3D%3Csql_password%3E" in text
    assert "PYTHONIOENCODING" in text
    assert "mssql+aioodbc://@." not in text
    assert "mssql+pyodbc://@." not in text


def test_tracked_docs_do_not_use_broken_sqlserver_netloc_urls():
    root = Path(__file__).resolve().parents[2]
    docs = [
        root / "backend" / ".env.example",
        root / "docs" / "SQLSERVER_MIGRATION_PLAN.md",
        root / "docs" / "DATABASE_MIGRATION.md",
    ]
    for path in docs:
        text = path.read_text(encoding="utf-8")
        assert "mssql+aioodbc://@" not in text
        assert "mssql+pyodbc://@" not in text
