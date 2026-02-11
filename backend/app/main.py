import os
from fastapi import FastAPI

from backend.app.api.routes.health import router as health_router
from backend.app.api.routes.schema import router as schema_router
from backend.app.api.routes.query import router as query_router
from backend.app.api.routes.ask import router as ask_router
from backend.app.api.routes.logs import router as logs_router
from backend.app.api.routes.eval import router as eval_router

API_PREFIX = "/api"
app = FastAPI(
    title="Arabic Analytics Copilot",
    version="0.1.0",
    description="Arabic -> SQL backend scaffold with Postgres semantic layer allowlist.",
)

def _is_true(v: str | None) -> bool:
    return (v or "").strip().lower() in ("1", "true", "yes", "y", "on")

STT_ENABLED = _is_true(os.getenv("STT_ENABLED", "0"))
STT_WARMUP = _is_true(os.getenv("STT_WARMUP", "0"))

@app.on_event("startup")
def startup_hooks():
    if not STT_ENABLED:
        print("[STT] disabled (STT_ENABLED=0)")
        return
    if not STT_WARMUP:
        print("[STT] warmup skipped (STT_WARMUP=0)")
        return
    try:
        from backend.app.services.stt.transcriber import _get_model
        _get_model()
        print("[STT] warmup ok")
    except Exception as e:
        print("[STT] warmup failed:", e)

@app.middleware("http")
async def force_utf8_json(request, call_next):
    response = await call_next(request)
    ct = response.headers.get("content-type", "")
    if ct.startswith("application/json") and "charset" not in ct.lower():
        response.headers["content-type"] = "application/json; charset=utf-8"
    return response

# Routers
app.include_router(health_router, prefix=API_PREFIX)
app.include_router(schema_router, prefix=API_PREFIX)
app.include_router(query_router, prefix=API_PREFIX)
app.include_router(ask_router, prefix=API_PREFIX)
app.include_router(logs_router, prefix=API_PREFIX)
app.include_router(eval_router, prefix=API_PREFIX)

# Transcribe router (conditional)
if STT_ENABLED:
    try:
        from backend.app.api.routes.transcribe import router as transcribe_router
        app.include_router(transcribe_router, prefix=API_PREFIX)
        print("[STT] router enabled")
    except Exception as e:
        print("[STT] router import failed, STT disabled:", e)
