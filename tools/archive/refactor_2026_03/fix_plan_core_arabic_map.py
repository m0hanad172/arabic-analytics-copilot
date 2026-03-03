from __future__ import annotations

import re
import shutil
from datetime import datetime
from pathlib import Path

P = Path("backend/app/services/ask/plan_core.py")

SAFE_LINE = '_ARABIC_DIGIT_MAP = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")\n'

def ts() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")

def main() -> None:
    if not P.exists():
        raise SystemExit(f"Not found: {P}")

    txt = P.read_text(encoding="utf-8", errors="ignore")
    bak = P.with_suffix(f".py.bak.{ts()}")
    shutil.copy2(P, bak)

    # Replace ANY _ARABIC_DIGIT_MAP assignment block (single-line or multi-line) with a safe one.
    # We replace from the line that starts with _ARABIC_DIGIT_MAP = up to the next blank line.
    new_txt, n = re.subn(
        r"(?ms)^\s*_ARABIC_DIGIT_MAP\s*=.*?(?:\n\s*\n)",
        SAFE_LINE + "\n",
        txt,
        count=1,
    )

    # If not found in that shape, try a looser replacement (until next 'def ').
    if n == 0:
        new_txt, n = re.subn(
            r"(?ms)^\s*_ARABIC_DIGIT_MAP\s*=.*?(?=^\s*def\s|\Z)",
            SAFE_LINE + "\n",
            txt,
            count=1,
        )

    if n == 0:
        raise SystemExit("Could not find _ARABIC_DIGIT_MAP assignment to patch in plan_core.py")

    P.write_text(new_txt, encoding="utf-8")
    print("✅ Patched plan_core.py (_ARABIC_DIGIT_MAP) safely")
    print(f"- Backup: {bak}")

if __name__ == "__main__":
    main()
