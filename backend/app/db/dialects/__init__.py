"""Pluggable SQL dialect layer (Phase A)."""
from backend.app.db.dialects.base import SqlDialect, get_dialect
from backend.app.db.dialects.postgres import PostgresDialect
from backend.app.db.dialects.sqlserver import SqlServerDialect

__all__ = ["SqlDialect", "get_dialect", "PostgresDialect", "SqlServerDialect"]
