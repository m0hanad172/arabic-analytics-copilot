"""Controlled SQL Server behaviour for /ask (Phase B).

When DATABASE_BACKEND=sqlserver, the /ask path must short-circuit with
HTTP 501 + a clear message instead of letting asyncpg surface a driver
error.
"""
import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend.app.core.config import settings
from backend.app.services.ask import runner as ask_runner


def test_ask_returns_501_on_sqlserver(monkeypatch):
    monkeypatch.setattr(settings, "database_backend", "sqlserver", raising=False)
    body = SimpleNamespace(question="ما هي مبيعات اليوم؟")

    with pytest.raises(HTTPException) as ei:
        asyncio.run(ask_runner.ask(body))

    assert ei.value.status_code == 501
    detail = ei.value.detail
    assert "Phase C" in detail
    assert "bi_meta" in detail
    assert "SQL Server" in detail


def test_ask_still_validates_empty_question_first():
    # 422 should win over the 501 short-circuit when the body is empty,
    # because the validation runs first and is the same on every backend.
    body = SimpleNamespace(question="   ")
    with pytest.raises(HTTPException) as ei:
        asyncio.run(ask_runner.ask(body))
    assert ei.value.status_code == 422
