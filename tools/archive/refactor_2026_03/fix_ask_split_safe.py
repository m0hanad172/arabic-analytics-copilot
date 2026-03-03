from __future__ import annotations

import shutil
from pathlib import Path

ASK = Path("backend/app/api/routes/ask.py")
BACKUPS = sorted(Path("backend/app/api/routes").glob("ask.py.bak.*"), key=lambda p: p.stat().st_mtime, reverse=True)

SERV_DIR = Path("backend/app/services/ask")
RUNNER = SERV_DIR / "runner.py"
INIT = SERV_DIR / "__init__.py"

def main():
    if not BACKUPS:
        raise SystemExit("ERROR: No ask.py.bak.* backup found. Cannot auto-recover.")
    backup = BACKUPS[0]

    # Ensure services dir
    SERV_DIR.mkdir(parents=True, exist_ok=True)
    if not INIT.exists():
        INIT.write_text("", encoding="utf-8")

    # Put the original full router file into runner.py (keeps router + decorators + any startup hooks)
    shutil.copy2(backup, RUNNER)

    # Make routes/ask.py a clean shim that exports router (and ask_router alias for safety)
    shim = """\
# Thin shim: keep routing stable, move implementation to services layer.
# The real router (with decorators/events) lives in backend.app.services.ask.runner

from backend.app.services.ask.runner import router

# Compatibility: some imports may expect ask_router
ask_router = router
"""
    ASK.write_text(shim, encoding="utf-8")

    print("✅ Safe split applied:")
    print(f"- Restored full router implementation to: {RUNNER}")
    print(f"- Replaced routes ask.py with shim: {ASK}")
    print(f"- Used latest backup: {backup}")
    print("\nNow restart the server and test /ask again.\n")

if __name__ == "__main__":
    main()
