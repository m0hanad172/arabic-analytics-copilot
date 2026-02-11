from __future__ import annotations

import re
import shutil
from datetime import datetime
from pathlib import Path

RUNNER = Path("backend/app/services/ask/runner.py")

TOP_HINTS_BLOCK = """
# Hints used by _infer_top_limit() to detect ranking/top-N questions (Arabic + common variants)
_TOP_HINTS = (
    "أعلى", "اعلى",
    "أفضل", "افضل",
    "الأعلى", "الاعلى",
    "الأفضل", "الافضل",
    "أكثر", "اكثر",
    "الأكثر", "الاكثر",
    "أكبر", "اكبر",
    "ترتيب", "رتّب", "رتب",
)
""".lstrip()


def ts() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def main() -> None:
    if not RUNNER.exists():
        raise SystemExit(f"runner not found: {RUNNER}")

    txt = RUNNER.read_text(encoding="utf-8", errors="ignore")

    # If already exists, do nothing
    if re.search(r"(?m)^\s*_TOP_HINTS\s*=", txt):
        print("✅ runner.py already defines _TOP_HINTS. Nothing to do.")
        return

    bak = RUNNER.with_suffix(f".py.bak.{ts()}")
    shutil.copy2(RUNNER, bak)

    # Insert right before def _infer_top_limit(...)
    m = re.search(r"(?m)^\s*def\s+_infer_top_limit\s*\(", txt)
    if not m:
        raise SystemExit("Could not locate def _infer_top_limit(...) in runner.py")

    idx = m.start()
    new_txt = txt[:idx] + TOP_HINTS_BLOCK + "\n" + txt[idx:]

    RUNNER.write_text(new_txt, encoding="utf-8")
    print("✅ Patched runner.py: inserted _TOP_HINTS before _infer_top_limit()")
    print(f"- Backup: {bak}")


if __name__ == "__main__":
    main()
