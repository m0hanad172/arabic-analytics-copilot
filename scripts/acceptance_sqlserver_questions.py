"""Run SQL Server production acceptance questions in-process.

This optional live script reads MSSQL_* from the environment, builds a
SQLAlchemy aioodbc odbc_connect URL, calls the FastAPI app with TestClient,
and checks the SQL Server acceptance gates. It never prints passwords.

Run:
    python scripts/acceptance_sqlserver_questions.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import quote_plus

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from backend.app.db.sqlserver_connect import (
    build_connection_string,
    default_named_instance_server,
    resolve_database_from_env,
    resolve_driver_from_env,
    resolve_sql_auth_from_env,
)


_ACCEPTANCE_DATABASE_URL = ""
_ACCEPTANCE_AUTH_MODE = "Windows trusted"


def _build_sqlserver_database_url() -> tuple[str, str]:
    server = os.environ.get("MSSQL_SERVER") or default_named_instance_server()
    sql_user, sql_password = resolve_sql_auth_from_env()
    odbc = build_connection_string(
        resolve_driver_from_env("ODBC Driver 18 for SQL Server") or "ODBC Driver 18 for SQL Server",
        server,
        database=resolve_database_from_env(),
        trusted=True,
        user=sql_user,
        password=sql_password,
        trust_server_cert=True,
        encrypt=False,
    )
    auth_mode = "SQL auth" if sql_user and sql_password else "Windows trusted"
    return "mssql+aioodbc:///?odbc_connect=" + quote_plus(odbc), auth_mode


def _apply_sqlserver_env() -> None:
    os.environ["DATABASE_BACKEND"] = "sqlserver"
    os.environ["COMPILER_BACKEND"] = "python"
    os.environ["STT_WARMUP"] = "0"
    os.environ["DATABASE_URL"] = _ACCEPTANCE_DATABASE_URL


def _refresh_imported_app_config() -> None:
    """Keep this script's env override ahead of backend/.env.

    backend.app.main loads backend/.env during import. Re-applying the script
    env and refreshing the already-created settings/session objects ensures
    MSSQL_* SQL-auth settings win for this in-process TestClient run only.
    """
    _apply_sqlserver_env()

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from backend.app.core.config import settings
    from backend.app.db import session as db_session

    settings.database_backend = "sqlserver"
    settings.compiler_backend = "python"
    settings.database_url = _ACCEPTANCE_DATABASE_URL

    db_session.engine = create_async_engine(
        _ACCEPTANCE_DATABASE_URL,
        pool_pre_ping=True,
    )
    db_session.SessionLocal = async_sessionmaker(
        db_session.engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )


_ACCEPTANCE_DATABASE_URL, _ACCEPTANCE_AUTH_MODE = _build_sqlserver_database_url()
_apply_sqlserver_env()


QUESTIONS = [
    "\u0627\u0639\u0631\u0636 \u0639\u062f\u062f \u0627\u0644\u0637\u0644\u0628\u0627\u062a \u062d\u0633\u0628 \u0627\u0644\u0645\u062f\u064a\u0646\u0629 \u0648\u0627\u0639\u0631\u0636 \u0623\u0639\u0644\u0649 5",
    "\u0627\u0639\u0631\u0636 \u0627\u0644\u0645\u0628\u064a\u0639\u0627\u062a \u062d\u0633\u0628 \u0627\u0644\u0633\u0646\u0629",
    "\u0627\u0639\u0631\u0636 \u0627\u0644\u0631\u0628\u062d \u062d\u0633\u0628 \u0641\u0626\u0629 \u0627\u0644\u0645\u0646\u062a\u062c",
    "\u0627\u0639\u0631\u0636 \u0623\u0639\u0644\u0649 10 \u0645\u0646\u062a\u062c\u0627\u062a \u062d\u0633\u0628 \u0627\u0644\u0645\u0628\u064a\u0639\u0627\u062a",
    "\u0627\u0639\u0631\u0636 \u0627\u0644\u062e\u0635\u0648\u0645\u0627\u062a \u062d\u0633\u0628 \u0641\u0626\u0629 \u0627\u0644\u0645\u0646\u062a\u062c",
    "\u0627\u0639\u0631\u0636 \u0627\u0644\u0645\u0628\u064a\u0639\u0627\u062a \u062d\u0633\u0628 \u0627\u0644\u0648\u0644\u0627\u064a\u0629",
    "\u0627\u0639\u0631\u0636 \u0639\u062f\u062f \u0627\u0644\u0637\u0644\u0628\u0627\u062a \u062d\u0633\u0628 \u0646\u0648\u0639 \u0627\u0644\u0639\u0645\u064a\u0644",
    "\u0627\u0639\u0631\u0636 \u0635\u0627\u0641\u064a \u0627\u0644\u0645\u0628\u064a\u0639\u0627\u062a \u0648\u0627\u0644\u0631\u0628\u062d \u0627\u0644\u0625\u062c\u0645\u0627\u0644\u064a \u0648\u0625\u062c\u0645\u0627\u0644\u064a \u0627\u0644\u062e\u0635\u0648\u0645\u0627\u062a \u0648\u0639\u062f\u062f \u0627\u0644\u0637\u0644\u0628\u0627\u062a \u062d\u0633\u0628 \u0627\u0633\u0645 \u0627\u0644\u0645\u0646\u062a\u062c \u0648\u0627\u0644\u0631\u0628\u0639 \u0645\u0646 \u0645\u062f\u064a\u0646\u0629 \u0633\u064a\u062f\u0646\u064a \u062e\u0644\u0627\u0644 \u0633\u0646\u0629 2015\u060c \u0648\u0631\u062a\u0628 \u0627\u0644\u0646\u062a\u0627\u0626\u062c \u062d\u0633\u0628 \u0627\u0644\u0631\u0628\u062d \u0627\u0644\u0625\u062c\u0645\u0627\u0644\u064a \u062a\u0646\u0627\u0632\u0644\u064a\u0627\u064b \u0648\u0627\u0639\u0631\u0636 \u0623\u0648\u0644 8 \u0635\u0641\u0648\u0641 \u0641\u0642\u0637",
]

# Q1-Q7 are deterministic rule-based acceptance checks. Q8 exercises the
# product UI path with use_llm=1 while the post-plan corrections still make it
# safe if the LLM omits limit/year details.
USE_LLM_BY_QUESTION = {
    1: 0,
    2: 0,
    3: 0,
    4: 0,
    5: 0,
    6: 0,
    7: 0,
    8: 1,
}


def _configure_sqlserver_env() -> None:
    _apply_sqlserver_env()
    print(f"SQL Server acceptance mode: {_ACCEPTANCE_AUTH_MODE}")


def _assert_common_sql(sql: str) -> None:
    upper = " ".join((sql or "").upper().split())
    forbidden = ["LIMIT ", "::BIGINT", "::NUMERIC", " ILIKE ", "JSONB", "AND AND", "WHERE AND", "OR OR", "WHERE OR"]
    for token in forbidden:
        if token in upper:
            raise AssertionError(f"Forbidden SQL token found: {token}")


def _assert_common_meta(meta: dict) -> None:
    if meta.get("compiler_backend") != "python":
        raise AssertionError("compiler_backend is not python")
    if meta.get("catalog_source") != "sqlserver_tables":
        raise AssertionError("catalog_source is not sqlserver_tables")
    if meta.get("skipped_for_sqlserver") is not None:
        raise AssertionError("SQL Server side channels were skipped")
    if meta.get("log_id") is None:
        raise AssertionError("query_log id missing")


def _assert_complex_sql(sql: str) -> None:
    checks = [
        ("TOP (8)", "TOP (8)" in sql),
        ("Sydney city filter", "f.city IN ('Sydney')" in sql or "f.city = 'Sydney'" in sql),
        (
            "2015 year filter",
            "DATEPART(year, f.order_date_d) IN (2015)" in sql
            or "DATEPART(year, f.order_date_d) = 2015" in sql,
        ),
        ("gross_profit metric", "gross_profit" in sql),
        ("discount_amount metric", "discount_amount" in sql),
        ("order_count metric", "order_count" in sql),
        ("gross_profit sort", "ORDER BY [gross_profit] DESC" in sql),
    ]
    for label, ok in checks:
        if not ok:
            raise AssertionError(f"Complex SQL check failed: {label}\nSQL: {sql}")


def _assert_customer_type_sql(sql: str) -> None:
    checks = [
        ("customer_type select", "f.customer_type AS [customer_type]" in sql),
        ("order_count metric", "COUNT_BIG(*) AS [order_count]" in sql),
        ("customer_type grouping", "GROUP BY f.customer_type" in sql),
    ]
    for label, ok in checks:
        if not ok:
            raise AssertionError(f"Customer type SQL check failed: {label}\nSQL: {sql}")


def main() -> int:
    _configure_sqlserver_env()

    from fastapi.testclient import TestClient

    from backend.app.main import app
    _refresh_imported_app_config()

    with TestClient(app) as client:
        health = client.get("/api/health")
        print(f"GET /api/health -> {health.status_code}")
        if health.status_code != 200:
            print(health.text[:1200])
            return 1

        for idx, question in enumerate(QUESTIONS, start=1):
            print()
            print(f"=== Acceptance Q{idx} ===")
            print(question)
            use_llm = int(USE_LLM_BY_QUESTION.get(idx, 0))
            print(f"use_llm: {use_llm}")
            response = client.post(
                "/api/ask",
                params={"use_llm": use_llm, "use_cache": 0, "explain": 0},
                json={"question": question},
            )
            print(f"status: {response.status_code}")
            if response.status_code != 200:
                print(response.text[:1600])
                return 1

            payload = response.json()
            meta = payload.get("meta") or {}
            result = payload.get("result") or {}
            sql = result.get("sql") or ""
            rows = result.get("rows") or []
            print(f"log_id: {meta.get('log_id')}")
            print(f"used_cache: {meta.get('used_cache')}")
            print(f"row_count: {len(rows)}")
            print(f"SQL: {sql}")
            _assert_common_meta(meta)
            _assert_common_sql(sql)
            if idx == 7:
                _assert_customer_type_sql(sql)
            if idx == len(QUESTIONS):
                _assert_complex_sql(sql)

        print()
        print("=== Cache acceptance recheck ===")
        first = QUESTIONS[0]
        warm = client.post(
            "/api/ask",
            params={"use_llm": 0, "use_cache": 1, "explain": 0},
            json={"question": first},
        )
        if warm.status_code != 200:
            print(warm.text[:1200])
            return 1
        repeat = client.post(
            "/api/ask",
            params={"use_llm": 0, "use_cache": 1, "explain": 0},
            json={"question": first},
        )
        if repeat.status_code != 200:
            print(repeat.text[:1200])
            return 1
        meta = repeat.json().get("meta") or {}
        print(f"repeat used_cache: {meta.get('used_cache')}")
        print(f"repeat log_id: {meta.get('log_id')}")
        if meta.get("used_cache") is not True:
            raise AssertionError("Repeated acceptance question did not use plan_cache")
        if meta.get("log_id") is None:
            raise AssertionError("Repeated acceptance question did not create query_log")

    print()
    print("SQL Server acceptance checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
