from __future__ import annotations

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

    # Only patch if runner.py uses @router.* and router isn't defined
    if "@router." not in src:
        print("ℹ️ No @router.* found in runner.py. Nothing to patch.")
        return

    if "router = APIRouter" in src:
        print("ℹ️ router already defined in runner.py. Nothing to patch.")
        return

    lines = src.splitlines(True)

    # Ensure APIRouter import exists (we add a minimal safe import line)
    has_apirouter = any(
        ln.lstrip().startswith("from fastapi import") and "APIRouter" in ln
        for ln in lines
    )
    if not has_apirouter:
        # Insert after last import line
        insert_at = 0
        for i, ln in enumerate(lines):
            if ln.startswith("import ") or ln.startswith("from "):
                insert_at = i + 1
            else:
                break
        lines.insert(insert_at, "from fastapi import APIRouter\n")

    # Insert router definition before the FIRST decorator usage
    first_router_idx = None
    for i, ln in enumerate(lines):
        if ln.lstrip().startswith("@router."):
            first_router_idx = i
            break

    if first_router_idx is None:
        print("ℹ️ No '@router.' line found after split. Nothing to patch.")
        return

    lines.insert(first_router_idx, 'router = APIRouter(tags=["ask"])\n\n')

    b = backup(RUNNER)
    RUNNER.write_text("".join(lines), encoding="utf-8")

    print("✅ Patched runner.py: inserted router definition before first @router.*")
    print(f"- Backup: {b}")


if __name__ == "__main__":
    main()
