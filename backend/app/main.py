from fastapi import FastAPI
from backend.app.api.routes.health import router as health_router
from backend.app.api.routes.schema import router as schema_router
from backend.app.api.routes.query import router as query_router
from backend.app.api.routes.ask import router as ask_router
from backend.app.api.routes.logs import router as logs_router
from backend.app.api.routes.eval import router as eval_router


app = FastAPI(
    title="Arabic Analytics Copilot (Phase 2)",
    version="0.1.0",
    description="Arabic -> SQL backend scaffold with Postgres semantic layer allowlist."
)

app.include_router(ask_router)

@app.middleware("http")
async def force_utf8_json(request, call_next):
    response = await call_next(request)
    ct = response.headers.get("content-type", "")
    if ct.startswith("application/json") and "charset" not in ct.lower():
        response.headers["content-type"] = "application/json; charset=utf-8"
    return response

app.include_router(health_router)
app.include_router(schema_router)
app.include_router(query_router)
app.include_router(logs_router)
app.include_router(eval_router)
