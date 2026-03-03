from __future__ import annotations

import re
import shutil
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

DB_FILE = ROOT / "backend" / "app" / "services" / "ask" / "db.py"
CACHE_FILE = ROOT / "backend" / "app" / "services" / "ask" / "cache.py"

def ts() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")

def backup(p: Path) -> Path:
    b = p.with_suffix(p.suffix + f".bak.{ts()}")
    shutil.copy2(p, b)
    return b

def ensure_db_facade():
    if DB_FILE.exists():
        return

    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    DB_FILE.write_text(
        """from __future__ import annotations

from typing import Any, Optional

# NOTE:
# This is a SAFE facade to avoid circular imports.
# We keep the real DB helpers in runner.py for now, but expose them here via lazy imports.
# Later, we can move the actual DB layer into this module cleanly.

async def _db_fetchval(sql: str, *args) -> Any:
    from .runner import _db_fetchval as impl
    return await impl(sql, *args)

async def _db_fetchrow(sql: str, *args) -> Optional[dict]:
    from .runner import _db_fetchrow as impl
    return await impl(sql, *args)

async def _db_fetch(sql: str, *args) -> list[dict]:
    from .runner import _db_fetch as impl
    return await impl(sql, *args)
""",
        encoding="utf-8",
    )

def insert_import_after_imports(text: str, import_line: str) -> str:
    if import_line in text:
        return text

    lines = text.splitlines(True)
    i = 0

    # Skip optional module docstring
    if lines and lines[0].lstrip().startswith(('"""', "'''")):
        quote = lines[0].lstrip()[:3]
        i = 1
        while i < len(lines) and quote not in lines[i]:
            i += 1
        if i < len(lines):
            i += 1  # include closing docstring line

    # Skip blank lines
    while i < len(lines) and lines[i].strip() == "":
        i += 1

    # Consume import block
    while i < len(lines) and (lines[i].lstrip().startswith("import ") or lines[i].lstrip().startswith("from ")):
        i += 1

    # Ensure one blank line after imports
    insert_at = i
    out = lines[:insert_at] + [import_line + "\n"] + lines[insert_at:]
    return "".join(out)

def ensure_ensure_json_obj(text: str) -> str:
    if "_ensure_json_obj" not in text:
        return text
    if re.search(r"^def\s+_ensure_json_obj\s*\(", text, flags=re.M):
        return text

    helper = """
def _ensure_json_obj(val):
    \"\"\"Return a dict from JSON-ish DB values (dict/str/None).\"\"\"
    if val is None:
        return {}
    if isinstance(val, dict):
        return val
    if isinstance(val, str):
        try:
            import json
            obj = json.loads(val)
            return obj if isinstance(obj, dict) else {}
        except Exception:
            return {}
    return {}
"""
    # Put helper near top (after imports)
    return insert_import_after_imports(text, helper.strip("\n"))

def patch_cache():
    if not CACHE_FILE.exists():
        raise SystemExit(f"cache.py not found: {CACHE_FILE}")

    original = CACHE_FILE.read_text(encoding="utf-8")
    b = backup(CACHE_FILE)

    text = original

    # Remove any runner imports for db helpers (module-level or inside functions)
    patterns = [
        r"^\s*from\s+\.runner\s+import\s+.*_db_fetchval.*$",
        r"^\s*from\s+\.runner\s+import\s+.*_db_fetchrow.*$",
        r"^\s*from\s+\.runner\s+import\s+.*_db_fetch\b.*$",
        r"^\s*from\s+\.runner\s+import\s+_db_fetchval\s*,\s*_db_fetchrow.*$",
        r"^\s*from\s+\.runner\s+import\s+_db_fetchrow\s*,\s*_db_fetchval.*$",
    ]
    for pat in patterns:
        text = re.sub(pat + r"\n?", "", text, flags=re.M)

    # Ensure cache imports db helpers from .db
    text = insert_import_after_imports(text, "from .db import _db_fetchval, _db_fetchrow, _db_fetch")

    # If cache uses _ensure_json_obj but doesn't define it, add a local helper
    text = ensure_ensure_json_obj(text)

    if text != original:
        CACHE_FILE.write_text(text, encoding="utf-8")
        print("✅ Patched cache.py to use db facade")
        print(f"- Backup: {b}")
    else:
        print("ℹ️ No changes needed in cache.py")

def main():
    ensure_db_facade()
    print(f"✅ Ensured db facade: {DB_FILE}")

    patch_cache()

    print("\nNext:")
    print("  python -m py_compile backend/app/services/ask/db.py")
    print("  python -m py_compile backend/app/services/ask/cache.py")
    print("  powershell -ExecutionPolicy Bypass -File tools/ask_suite.ps1")

if __name__ == "__main__":
    main()
