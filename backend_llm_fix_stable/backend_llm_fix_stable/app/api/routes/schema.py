from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from backend.app.db.session import get_session
from backend.app.models.schemas import CatalogResponse
from backend.app.core.config import settings
from backend.app.services.catalog_cache import get_catalog, refresh_catalog

router = APIRouter(tags=["schema"])

@router.get("/schema", response_model=CatalogResponse)
async def get_schema(session: AsyncSession = Depends(get_session)):
    catalog = await get_catalog(session)
    return {"allowed_schema": settings.allowed_schema, "catalog": catalog}

@router.post("/schema/refresh", response_model=CatalogResponse)
async def refresh_schema(session: AsyncSession = Depends(get_session)):
    catalog = await refresh_catalog(session)
    return {"allowed_schema": settings.allowed_schema, "catalog": catalog}
