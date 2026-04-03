from __future__ import annotations

import inspect
from fastapi import APIRouter, Query
from pydantic import BaseModel

from backend.app.services.ask import runner as ask_runner

try:
    from backend.app.models.schemas import AskRequest  # type: ignore
except Exception:
    class AskRequestFallback(BaseModel):
        question: str
    AskRequest = AskRequestFallback

from backend.app.services.ask.runner import *  # noqa: F401,F403

router = APIRouter(prefix="/ask", tags=["ask"])


@router.post("")
async def ask_endpoint(
    body: AskRequest,
    use_llm: int = Query(0),
    use_cache: int = Query(1),
    debug_sql: int = Query(0),
    explain: int = Query(0),


    llm_mode: str = Query("", description="LLM mode: '' (default) | 'mock'"),
):
    fn = ask_runner.ask
    sig = inspect.signature(fn)
    params = sig.parameters

    kwargs = {}

    if "body" in params:
        kwargs["body"] = body
    elif "question" in params:
        kwargs["question"] = getattr(body, "question", None)

    if "use_llm" in params:
        kwargs["use_llm"] = use_llm
    if "use_cache" in params:
        kwargs["use_cache"] = use_cache
    if "debug_sql" in params:
        kwargs["debug_sql"] = debug_sql
    if "explain" in params:
        kwargs["explain"] = explain


    if "llm_mode" in params:
        kwargs["llm_mode"] = llm_mode

    return await fn(**kwargs)
