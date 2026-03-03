from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
import re

RUNNER = Path("backend/app/services/ask/runner.py")

def ts() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")

def insert_import_after_imports(text: str, import_line: str) -> str:
    if import_line.strip() in text:
        return text

    lines = text.splitlines(keepends=True)

    # Skip shebang/comments
    i = 0
    while i < len(lines) and (lines[i].startswith("#!") or lines[i].strip().startswith("#")):
        i += 1

    # Skip module docstring if any
    if i < len(lines) and lines[i].lstrip().startswith(('"""', "'''")):
        q = '"""' if lines[i].lstrip().startswith('"""') else "'''"
        i += 1
        while i < len(lines):
            if q in lines[i]:
                i += 1
                break
            i += 1

    # Move past existing imports block
    while i < len(lines):
        s = lines[i].strip()
        if not s or s.startswith("#") or s.startswith(("import ", "from ")):
            i += 1
            continue
        break

    lines.insert(i, import_line if import_line.endswith("\n") else import_line + "\n")
    return "".join(lines)

def main() -> None:
    if not RUNNER.exists():
        raise SystemExit(f"runner not found: {RUNNER}")

    txt = RUNNER.read_text(encoding="utf-8", errors="ignore")

    # If runner already defines _ARABIC_DIGIT_MAP, no need.
    if re.search(r"(?m)^\s*_ARABIC_DIGIT_MAP\s*=", txt):
        print("✅ runner.py already defines _ARABIC_DIGIT_MAP. Nothing to do.")
        return

    bak = RUNNER.with_suffix(f".py.bak.{ts()}")
    shutil.copy2(RUNNER, bak)

    # Import the constant from plan_core (no circular import)
    txt = insert_import_after_imports(txt, "from .plan_core import _ARABIC_DIGIT_MAP\n")

    RUNNER.write_text(txt, encoding="utf-8")
    print("✅ Patched runner.py to import _ARABIC_DIGIT_MAP from plan_core.py")
    print(f"- Backup: {bak}")

if __name__ == "__main__":
    main()
