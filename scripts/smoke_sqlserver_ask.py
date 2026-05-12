"""Live SQL Server smoke test for /ask (Phase C4).

Boots the FastAPI app in-process with SQL Server env overrides, hits
/api/health and /api/ask for three Arabic questions, and prints a
compact summary. Does not require uvicorn or external HTTP.

Run with:
    python scripts/smoke_sqlserver_ask.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ---- Override env BEFORE importing the app -------------------------------
from urllib.parse import quote_plus

os.environ["DATABASE_BACKEND"] = "sqlserver"
os.environ["COMPILER_BACKEND"] = "python"

# The named-instance backslash ".\SQLEXPRESS" cannot survive a netloc
# URL: %5C gets re-encoded and aioodbc receives a literal "%5C" in the
# SERVER. SQLAlchemy's recommended workaround is odbc_connect=, which
# passes the raw ODBC connection string through unchanged.
_ODBC = (
    "DRIVER={ODBC Driver 18 for SQL Server};"
    r"SERVER=.\SQLEXPRESS;"
    "DATABASE=ArabicAnalytics;"
    "Trusted_Connection=yes;"
    "TrustServerCertificate=yes;"
    "Encrypt=no;"
)
os.environ["DATABASE_URL"] = (
    "mssql+aioodbc:///?odbc_connect=" + quote_plus(_ODBC)
)
# Skip Whisper warmup (it shells out to a multi-GB model).
os.environ["STT_WARMUP"] = "0"


def main() -> int:
    from fastapi.testclient import TestClient

    from backend.app.main import app

    questions = [
        "اعرض عدد الطلبات حسب المدينة واعرض أعلى 5",
        "اعرض المبيعات حسب السنة",
        "اعرض الربح حسب فئة المنتج",
    ]

    with TestClient(app) as client:
        r = client.get("/api/health")
        print(f"GET /api/health -> {r.status_code} {r.json() if r.is_success else r.text}")

        for q in questions:
            print()
            print(f"=== Q: {q} ===")
            r = client.post(
                "/api/ask",
                params={"use_llm": 0, "use_cache": 0, "explain": 0},
                json={"question": q},
            )
            print(f"  status: {r.status_code}")
            if r.status_code != 200:
                print(f"  body: {r.text[:1200]}")
                continue
            out = r.json()
            meta = out.get("meta") or {}
            res = out.get("result") or {}
            sql = res.get("sql", "")
            rows = res.get("rows") or []
            print(f"  compiler_backend:    {meta.get('compiler_backend')}")
            print(f"  catalog_source:      {meta.get('catalog_source')}")
            print(f"  skipped_for_sqlserver: {meta.get('skipped_for_sqlserver')}")
            print(f"  row_count:           {len(rows)}")
            print(f"  SQL:                 {sql}")
            print(f"  first row:           {rows[0] if rows else None}")
            # Phase C4 hard requirements:
            sql_upper = sql.upper()
            checks = [
                ("contains TOP (", "TOP (" in sql_upper),
                ("no LIMIT n",     "LIMIT " not in sql_upper or not any(c.isdigit() for c in sql_upper.split("LIMIT", 1)[1][:5]) if "LIMIT" in sql_upper else True),
                ("no ::bigint",    "::BIGINT" not in sql_upper),
                ("no ::numeric",   "::NUMERIC" not in sql_upper),
                ("no ILIKE",       "ILIKE" not in sql_upper),
                ("no jsonb",       "JSONB" not in sql_upper),
            ]
            for label, ok in checks:
                print(f"  check {label:18} -> {'OK' if ok else 'FAIL'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
