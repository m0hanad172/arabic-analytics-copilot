from __future__ import annotations

import re
from pathlib import Path


ASK_SHIM = Path("backend/app/api/routes/ask.py")
EVAL_PATH = Path("backend/app/api/routes/eval.py")
RUNNER = Path("backend/app/services/ask/runner.py")


def main() -> None:
    if not RUNNER.exists():
        raise SystemExit(f"ERROR: runner not found at {RUNNER}. Did you run the safe split script?")

    # 1) Make ask.py a compatibility re-export shim (so old imports keep working)
    shim = """\
# Compatibility shim:
# Keep old imports working (eval.py and others may import _get_catalog, etc.)
# Real implementation lives in backend.app.services.ask.runner

from backend.app.services.ask.runner import *  # noqa: F401,F403

# Back-compat name used by main.py in some versions
ask_router = router
"""
    ASK_SHIM.write_text(shim, encoding="utf-8")
    print(f"✅ Patched: {ASK_SHIM} (re-export all + ask_router alias)")

    # 2) Patch eval.py to import from services layer (more professional; avoids routes internals)
    if not EVAL_PATH.exists():
        print(f"⚠️ eval.py not found at {EVAL_PATH} (skipping)")
        return

    txt = EVAL_PATH.read_text(encoding="utf-8", errors="ignore")

    # Replace: from backend.app.api.routes.ask import (...)  --> from backend.app.services.ask.runner import (...)
    new_txt = re.sub(
        r"from\s+backend\.app\.api\.routes\.ask\s+import\s*\(",
        "from backend.app.services.ask.runner import (",
        txt,
        flags=re.MULTILINE,
    )

    if new_txt != txt:
        EVAL_PATH.write_text(new_txt, encoding="utf-8")
        print(f"✅ Patched: {EVAL_PATH} (imports now point to services.ask.runner)")
    else:
        print("ℹ️ eval.py import pattern not changed (maybe already patched or different style).")

    print("\nDone. Restart uvicorn and it should boot normally.\n")


if __name__ == "__main__":
    main()
