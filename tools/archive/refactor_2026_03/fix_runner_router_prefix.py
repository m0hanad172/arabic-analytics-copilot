from __future__ import annotations

import re
import shutil
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "backend" / "app" / "services" / "ask" / "runner.py"


def ts() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def backup(p: Path) -> Path:
    b = p.with_suffix(p.suffix + f".bak.{ts()}")
    shutil.copy2(p, b)
    return b


def main() -> None:
    if not RUNNER.exists():
        raise SystemExit(f"runner.py not found: {RUNNER}")

    src = RUNNER.read_text(encoding="utf-8")

    m = re.search(r"router\s*=\s*APIRouter\s*\((.*?)\)", src, flags=re.DOTALL)
    if not m:
        print("ℹ️ No router = APIRouter(...) found. Nothing to patch.")
        return

    if "prefix=" in m.group(1):
        print("ℹ️ router already has prefix=. Nothing to patch.")
        return

    b = backup(RUNNER)

    # Insert prefix="/ask" as first kwarg
    src2 = re.sub(
        r"router\s*=\s*APIRouter\s*\(\s*",
        'router = APIRouter(prefix="/ask", ',
        src,
        count=1,
    )

    RUNNER.write_text(src2, encoding="utf-8")

    print('✅ Patched runner.py: added prefix="/ask" to router')
    print(f"- Backup: {b}")


if __name__ == "__main__":
    main()
