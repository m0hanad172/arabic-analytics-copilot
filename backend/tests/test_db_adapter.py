"""Tests for backend/app/db/adapter.py (Phase B)."""
import asyncio

import pytest

from backend.app.core.config import settings
from backend.app.db import adapter
from backend.app.db.adapter import (
    BackendNotSupportedError,
    active_backend,
    controlled_backend_error_message,
    ensure_json_obj,
    is_postgres,
    is_sqlserver,
    normalize_database_url_for_asyncpg,
    normalize_value,
)


# ---- Backend identification ------------------------------------------------

def test_default_backend_is_postgres(monkeypatch):
    # Isolate the documented default from a SQL Server-first local backend/.env.
    monkeypatch.setattr(settings, "database_backend", "postgres", raising=False)
    assert active_backend() == "postgres"
    assert is_postgres() is True
    assert is_sqlserver() is False


@pytest.mark.parametrize("alias", ["postgres", "POSTGRES", "Postgresql", "pg"])
def test_postgres_aliases_resolve(alias, monkeypatch):
    monkeypatch.setattr(settings, "database_backend", alias, raising=False)
    assert active_backend() == "postgres"
    assert is_postgres() is True


@pytest.mark.parametrize("alias", ["sqlserver", "MSSQL", "tsql", "mssqlserver"])
def test_sqlserver_aliases_resolve(alias, monkeypatch):
    monkeypatch.setattr(settings, "database_backend", alias, raising=False)
    assert active_backend() == "sqlserver"
    assert is_sqlserver() is True
    assert is_postgres() is False


def test_unknown_backend_falls_back_to_postgres(monkeypatch):
    monkeypatch.setattr(settings, "database_backend", "oracle", raising=False)
    assert active_backend() == "postgres"


# ---- URL helpers -----------------------------------------------------------

def test_normalize_database_url_strips_asyncpg_suffix():
    url = "postgresql+asyncpg://u:p@h:5432/db"
    assert normalize_database_url_for_asyncpg(url) == "postgresql://u:p@h:5432/db"


def test_normalize_database_url_passthrough_for_mssql():
    url = "mssql+aioodbc://u:p@h:1433/db"
    assert normalize_database_url_for_asyncpg(url) == url


def test_normalize_database_url_handles_empty():
    assert normalize_database_url_for_asyncpg("") == ""


# ---- Row helpers -----------------------------------------------------------

def test_normalize_value_decimal_to_float():
    from decimal import Decimal
    assert normalize_value(Decimal("1.5")) == 1.5


def test_normalize_value_float_rounded():
    assert normalize_value(0.999999999) == 1.0


def test_normalize_value_passthrough():
    assert normalize_value("abc") == "abc"
    assert normalize_value(7) == 7
    assert normalize_value(None) is None


def test_ensure_json_obj_parses_string_json():
    assert ensure_json_obj('{"a": 1}') == {"a": 1}


def test_ensure_json_obj_passthrough_for_dict():
    assert ensure_json_obj({"a": 1}) == {"a": 1}


def test_ensure_json_obj_returns_string_when_not_json():
    assert ensure_json_obj("not json") == "not json"


# ---- Controlled error ------------------------------------------------------

def test_controlled_error_message_mentions_phase_c_and_bi_meta():
    msg = controlled_backend_error_message()
    assert "Phase C" in msg
    assert "bi_meta" in msg
    assert "SQL Server" in msg


def test_pg_helpers_raise_backend_not_supported_on_sqlserver(monkeypatch):
    monkeypatch.setattr(settings, "database_backend", "sqlserver", raising=False)

    with pytest.raises(BackendNotSupportedError) as ei:
        asyncio.run(adapter.pg_fetchval("SELECT 1"))
    assert "Phase C" in str(ei.value)

    with pytest.raises(BackendNotSupportedError):
        asyncio.run(adapter.pg_fetchrow("SELECT 1"))

    with pytest.raises(BackendNotSupportedError):
        asyncio.run(adapter.pg_fetch("SELECT 1"))
