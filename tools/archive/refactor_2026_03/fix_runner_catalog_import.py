from __future__ import annotations

import re
import shutil
from datetime import datetime
from pathlib import Path

RUNNER = Path("backend/app/services/ask/runner.py")

def ts() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")

def main() -> None:
    if not RUNNER.exists():
        raise SystemExit(f"runner not found: {RUNNER}")

    txt = RUNNER.read_text(encoding="utf-8", errors="ignore")
    bak = RUNNER.with_suffix(f".py.bak.{ts()}")
    shutil.copy2(RUNNER, bak)

    # Replace any "from .catalog import ..." line and remove _ensure_key from the imported names.
    def repl(m: re.Match) -> str:
        names = m.group(1)
        parts = [p.strip() for p in names.split(",") if p.strip()]
        parts = [p for p in parts if p != "_ensure_key"]
        if not parts:
            return ""  # remove the line if nothing left
        return "from .catalog import " + ", ".join(parts) + "\n"

    new_txt, n = re.subn(
        r"^from\s+\.catalog\s+import\s+([^\n]+)\n",
        repl,
        txt,
        flags=re.MULTILINE,
    )

    if n == 0:
        print("ℹ️ No 'from .catalog import ...' line found. Nothing changed.")
        return

    RUNNER.write_text(new_txt, encoding="utf-8")
    print("✅ Patched runner.py successfully")
    print(f"- Backup: {bak}")
    print("- Removed _ensure_key from catalog import (it doesn't exist in catalog.py).")

if __name__ == "__main__":
    main()
