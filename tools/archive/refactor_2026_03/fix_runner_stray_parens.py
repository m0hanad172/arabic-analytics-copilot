from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path


RUNNER = Path("backend/app/services/ask/runner.py")


def ts() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def is_probably_import_paren_close(lines: list[str], i: int) -> bool:
    """
    Keep ')' if it is likely closing an import parenthesis block:
      from x import (
        ...
      )
    We'll look back up to ~12 lines for 'import ('.
    """
    for j in range(max(0, i - 12), i):
        s = lines[j].strip()
        if s.endswith("import (") or s.endswith("import(") or (" import (" in s):
            return True
    return False


def main() -> None:
    if not RUNNER.exists():
        raise SystemExit(f"Missing: {RUNNER}")

    txt = RUNNER.read_text(encoding="utf-8", errors="ignore")
    lines = txt.splitlines(True)

    removed = 0
    out: list[str] = []

    for i, line in enumerate(lines):
        if line.strip() == ")" and (line.startswith(")") or line.startswith(")\r") or line.startswith(")\n") or line == ")\r\n" or line == ")\n":
            # A top-level standalone ')'
            if not is_probably_import_paren_close(lines, i):
                removed += 1
                continue
        out.append(line)

    if removed == 0:
        print("ℹ️ No stray top-level ')' lines detected. No changes made.")
        return

    bak = RUNNER.with_suffix(f".py.bak.{ts()}")
    shutil.copy2(RUNNER, bak)
    RUNNER.write_text("".join(out), encoding="utf-8")

    print("✅ Fixed runner.py: removed stray top-level ')' lines")
    print(f"- Backup: {bak}")
    print(f"- Removed lines: {removed}")


if __name__ == "__main__":
    main()
