from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASK_ROUTE = ROOT / "backend" / "app" / "api" / "routes" / "ask.py"


def ts() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def backup(p: Path) -> Path:
    b = p.with_suffix(p.suffix + f".bak.{ts()}")
    shutil.copy2(p, b)
    return b


ASK_PY = r'''from __future__ import annotations

import inspect
from fastapi import APIRouter, Query
from pydantic import BaseModel

# Import runner module (service layer)
from backend.app.services.ask import runner as ask_runner

# Try to reuse the official request model (if exists)
try:
    from backend.app.models.schemas import AskRequest  # type: ignore
except Exception:
    class AskRequest(BaseModel):
        question: str

# Re-export legacy helper symbols that other modules (e.g., eval.py) may import
# Keep this AFTER importing ask_runner, but BEFORE defining our router.
from backend.app.services.ask.runner import *  # noqa: F401,F403

router = APIRouter(prefix="/ask", tags=["ask"])


@router.post("")
async def ask_endpoint(
    body: AskRequest,
    use_llm: int = Query(0),
    use_cache: int = Query(1),
    debug_sql: int = Query(0),
    explain: int = Query(0),
):
    """
    Stable API wrapper:
    - Always accepts JSON body with {"question": "..."}.
    - Dispatches to ask_runner.ask with whatever signature it currently has.
    """
    fn = ask_runner.ask
    sig = inspect.signature(fn)
    params = sig.parameters

    kwargs = {}

    # body / question routing
    if "body" in params:
        kwargs["body"] = body
    elif "question" in params:
        kwargs["question"] = getattr(body, "question", None)

    # optional flags (only pass if the function expects them)
    if "use_llm" in params:
        kwargs["use_llm"] = use_llm
    if "use_cache" in params:
        kwargs["use_cache"] = use_cache
    if "debug_sql" in params:
        kwargs["debug_sql"] = debug_sql
    if "explain" in params:
        kwargs["explain"] = explain

    return await fn(**kwargs)
'''


def main() -> None:
    if not ASK_ROUTE.exists():
        raise SystemExit(f"ask.py not found: {ASK_ROUTE}")

    b = backup(ASK_ROUTE)
    ASK_ROUTE.write_text(ASK_PY, encoding="utf-8")
    print("✅ Restored backend/app/api/routes/ask.py as a stable API wrapper (fixes 422)")
    print(f"- Backup: {b}")


if __name__ == "__main__":
    main()
