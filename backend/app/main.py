from pathlib import Path
import os

try:
    from dotenv import load_dotenv

    # backend/app/main.py -> backend/.env
    _ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
    load_dotenv(_ENV_PATH, override=False)
except Exception:
    pass

from fastapi import FastAPI

from backend.app.api.routes.health import router as health_router
from backend.app.api.routes.schema import router as schema_router
from backend.app.api.routes.query import router as query_router
from backend.app.api.routes.ask import router as ask_router
from backend.app.api.routes.logs import router as logs_router
from backend.app.api.routes.eval import router as eval_router
from backend.app.api.routes.transcribe import router as transcribe_router

from backend.app.services.stt.transcriber import _get_model
from pathlib import Path
from dotenv import load_dotenv

ENV_PATH = Path(__file__).resolve().parents[2] / ".env"  # backend/.env
load_dotenv(ENV_PATH, override=True)

API_PREFIX = "/api"
app = FastAPI(
    title="Arabic Analytics Copilot (Phase 2)",
    version="0.1.0",
    description="Arabic -> SQL backend scaffold with Postgres semantic layer allowlist.",
)


@app.on_event("startup")
def warmup_whisper():
    if os.getenv("STT_WARMUP", "1") != "1":
        print("[STT] warmup skipped")
        return
    try:
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
app.include_router(transcribe_router, prefix=API_PREFIX)
