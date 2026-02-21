import pytest
from backend.app.core.sql_guardrails import guard_sql_or_raise

def test_guardrails_blocks_multi_statement():
    with pytest.raises(ValueError):
        guard_sql_or_raise(
            "SELECT 1; SELECT 2;",
            max_rows=200,
            allowed_schemas={"bi"},
        )
