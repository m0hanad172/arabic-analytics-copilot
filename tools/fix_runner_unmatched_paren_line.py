from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path


RUNNER = Path("backend/app/services/ask/runner.py")
LINE_NO = 551  # from your traceback


def ts() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def main() -> None:
    if not RUNNER.exists():
        raise SystemExit(f"Missing: {RUNNER}")

    lines = RUNNER.read_text(encoding="utf-8", errors="ignore").splitlines(True)
    idx = LINE_NO - 1

    if idx < 0 or idx >= len(lines):
        raise SystemExit(f"Line {LINE_NO} out of range (file has {len(lines)} lines).")

    target = lines[idx]
    if target.strip() != ")":
        # Don't touch anything if it's not exactly a standalone ')'
        print("❌ Not touching runner.py")
        print(f"Line {LINE_NO} is not a standalone ')'. It is:\n{target!r}")
        return

    bak = RUNNER.with_suffix(f".py.bak.{ts()}")
    shutil.copy2(RUNNER, bak)

    del lines[idx]
    RUNNER.write_text("".join(lines), encoding="utf-8")

    print("✅ Removed unmatched standalone ')' line")
    print(f"- File  : {RUNNER}")
    print(f"- Line  : {LINE_NO}")
    print(f"- Backup: {bak}")


if __name__ == "__main__":
    main()
