from __future__ import annotations

import asyncio
import json

from backend.app.core.config import settings
from backend.app.services.ask import cache_log


class _FakeResult:
    def __init__(self, *, mapping=None, scalar=None):
        self._mapping = mapping
        self._scalar = scalar

    def mappings(self):
        return self

    def first(self):
        return self._mapping

    def scalar_one_or_none(self):
        return self._scalar


class _FakeSession:
    def __init__(self, result: _FakeResult):
        self.result = result
        self.executed: list[tuple[str, dict | None]] = []
        self.commits = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self, statement, params=None):
        self.executed.append((str(statement), params))
        return self.result

    async def commit(self):
        self.commits += 1


def _install_session(monkeypatch, fake: _FakeSession) -> None:
    from backend.app.db import session as db_session

    monkeypatch.setattr(db_session, "SessionLocal", lambda: fake)


def test_postgres_cache_log_preserves_existing_sql(monkeypatch):
    monkeypatch.setattr(settings, "database_backend", "postgres", raising=False)

    captured: list[tuple[str, tuple]] = []

    async def fake_fetchrow(sql, *args):
        captured.append((sql, args))
        return {"id": 7, "plan": '{"metrics":["net_sales"]}', "model": "rule_based"}

    async def fake_fetchval(sql, *args):
        captured.append((sql, args))
        return 99

    row = asyncio.run(
        cache_log.get_cached_plan(
            "q",
            "hash",
            pg_fetchrow_func=fake_fetchrow,
        )
    )
    assert row["plan"] == {"metrics": ["net_sales"]}
    assert "WHERE question_norm=$1 AND catalog_hash=$2" in captured[-1][0]
    assert "LIMIT 1" in captured[-1][0]

    asyncio.run(
        cache_log.upsert_cached_plan(
            "q",
            "raw",
            "hash",
            {"dimensions": ["city"]},
            "rule_based",
            pg_fetchval_func=fake_fetchval,
        )
    )
    assert "ON CONFLICT (question_norm, catalog_hash)" in captured[-1][0]
    assert "$4::jsonb" in captured[-1][0]

    log_id = asyncio.run(
        cache_log.insert_query_log(
            question="raw",
            plan={"metrics": ["net_sales"]},
            sql="SELECT 1;",
            row_count=1,
            warnings=[],
            suggestions={},
            duration_ms=5,
            used_cache=False,
            used_llm=False,
            explain_used=False,
            pg_fetchval_func=fake_fetchval,
        )
    )
    assert log_id == 99
    assert "RETURNING id" in captured[-1][0]
    assert "$2::jsonb" in captured[-1][0]
    assert "$5::jsonb" in captured[-1][0]


def test_sqlserver_get_cached_plan_uses_bracketed_plan(monkeypatch):
    monkeypatch.setattr(settings, "database_backend", "sqlserver", raising=False)
    fake = _FakeSession(
        _FakeResult(
            mapping={
                "id": 3,
                "plan": '{"metrics":["net_sales"],"dimensions":["city"]}',
                "model": "rule_based",
            }
        )
    )
    _install_session(monkeypatch, fake)

    row = asyncio.run(cache_log.get_cached_plan("q", "hash"))

    assert row["id"] == 3
    assert row["plan"] == {"metrics": ["net_sales"], "dimensions": ["city"]}
    sql, params = fake.executed[0]
    assert "SELECT TOP (1) id, [plan], model" in sql
    assert "question_norm = :question_norm" in sql
    assert params == {"question_norm": "q", "catalog_hash": "hash"}


def test_sqlserver_upsert_uses_merge_and_json_text(monkeypatch):
    monkeypatch.setattr(settings, "database_backend", "sqlserver", raising=False)
    fake = _FakeSession(_FakeResult())
    _install_session(monkeypatch, fake)

    asyncio.run(
        cache_log.upsert_cached_plan(
            "q",
            "raw",
            "hash",
            {"metrics": ["net_sales"]},
            "rule_based",
        )
    )

    sql, params = fake.executed[0]
    assert "MERGE bi_meta.plan_cache" in sql
    assert "WITH (HOLDLOCK)" in sql
    assert "source.[plan]" in sql
    assert "ON CONFLICT" not in sql
    assert json.loads(params["plan_json"]) == {"metrics": ["net_sales"]}
    assert fake.commits == 1


def test_sqlserver_insert_query_log_brackets_reserved_columns(monkeypatch):
    monkeypatch.setattr(settings, "database_backend", "sqlserver", raising=False)
    fake = _FakeSession(_FakeResult(scalar=42))
    _install_session(monkeypatch, fake)

    log_id = asyncio.run(
        cache_log.insert_query_log(
            question="raw",
            plan={"metrics": ["net_sales"]},
            sql="SELECT TOP (1) 1;",
            row_count=1,
            warnings=["warn"],
            suggestions={"next": "city"},
            duration_ms=7,
            used_cache=True,
            used_llm=False,
            explain_used=True,
        )
    )

    assert log_id == 42
    sql, params = fake.executed[0]
    assert "question, [plan], [sql], row_count" in sql
    assert "OUTPUT INSERTED.id" in sql
    assert json.loads(params["warnings_json"]) == ["warn"]
    assert json.loads(params["suggestions_json"]) == {"next": "city"}
    assert params["used_cache"] is True
    assert params["explain_used"] is True
    assert fake.commits == 1
