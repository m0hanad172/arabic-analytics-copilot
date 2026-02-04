from typing import Dict, List, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from backend.app.db.introspect import load_schema_catalog

_catalog: Optional[Dict[str, List[Dict[str, Any]]]] = None

async def get_catalog(session: AsyncSession) -> Dict[str, List[Dict[str, Any]]]:
    global _catalog
    if _catalog is None:
        _catalog = await load_schema_catalog(session)
    return _catalog

async def refresh_catalog(session: AsyncSession) -> Dict[str, List[Dict[str, Any]]]:
    global _catalog
    _catalog = await load_schema_catalog(session)
    return _catalog
