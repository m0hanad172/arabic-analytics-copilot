from __future__ import annotations

import re
import shutil
from datetime import datetime
from pathlib import Path

CACHE = Path("backend/app/services/ask/cache.py")

def ts() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")

def main() -> None:
    if not CACHE.exists():
        raise SystemExit(f"cache.py not found: {CACHE}")

    txt = CACHE.read_text(encoding="utf-8", errors="ignore")
    bak = CACHE.with_suffix(f".py.bak.{ts()}")
    shutil.copy2(CACHE, bak)

    # Determine which imports are needed based on usage
    needed = []
    if "re." in txt and not re.search(r"(?m)^\s*import\s+re\s*$", txt):
        needed.append("import re")
    if "json." in txt and not re.search(r"(?m)^\s*import\s+json\s*$", txt):
        needed.append("import json")
    if "Optional" in txt and not re.search(r"(?m)^\s*from\s+typing\s+import\s+.*Optional", txt):
        needed.append("from typing import Optional")
    if "Dict" in txt or "List" in txt or "Any" in txt:
        if not re.search(r"(?m)^\s*from\s+typing\s+import\s+.*(Dict|List|Any)", txt):
            needed.append("from typing import Any, Dict, List")

    # Insert imports after future import / header
    lines = txt.splitlines()
    out = []
    inserted = False

    for i, ln in enumerate(lines):
        out.append(ln)
        if not inserted and ln.strip().startswith("from __future__ import"):
            # add imports right after the future line
            out.append("")
            for imp in needed:
                out.append(imp)
            out.append("")
            inserted = True

    # If no future import, add at very top
    if not inserted and needed:
        out = needed + [""] + lines

    new_txt = "\n".join(out).rstrip() + "\n"
    CACHE.write_text(new_txt, encoding="utf-8")

    print("✅ Patched cache.py imports")
    print(f"- Backup: {bak}")
    if needed:
        print("- Added:")
        for imp in needed:
            print(f"  * {imp}")
    else:
        print("- No imports were needed (already present).")

if __name__ == "__main__":
    main()
