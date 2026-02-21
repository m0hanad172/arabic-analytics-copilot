from typing import Dict, List, Any
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from backend.app.core.config import settings

# Catalog structure: { "bi.view_name": [ {"name": "...", "type": "..."}, ... ] }
async def load_schema_catalog(session: AsyncSession) -> Dict[str, List[Dict[str, Any]]]:
    q = text("""
        SELECT table_schema, table_name, column_name, data_type, ordinal_position
        FROM information_schema.columns
        WHERE table_schema = :schema
        ORDER BY table_schema, table_name, ordinal_position;
    """)
    rows = (await session.execute(q, {"schema": settings.allowed_schema})).all()

    catalog: Dict[str, List[Dict[str, Any]]] = {}
    for table_schema, table_name, column_name, data_type, ordinal_position in rows:
        key = f"{table_schema}.{table_name}"
        catalog.setdefault(key, []).append(
            {"name": column_name, "type": data_type, "pos": int(ordinal_position)}
        )
    return catalog
