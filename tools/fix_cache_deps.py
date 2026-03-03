from __future__ import annotations

import re
import shutil
from datetime import datetime
from pathlib import Path

CACHE = Path("backend/app/services/ask/cache.py")

def ts() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")

def indent_of(s: str) -> int:
    return len(s) - len(s.lstrip(" \t"))

def patch_func(txt: str, func_name: str, inject_line: str) -> str:
    # find "async def func_name("
    m = re.search(rf"(?m)^\s*async\s+def\s+{re.escape(func_name)}\s*\(", txt)
    if not m:
        return txt

    lines = txt.splitlines(keepends=True)
    # locate line index of def
    def_line_idx = 0
    pos = 0
    for i, ln in enumerate(lines):
        pos += len(ln)
        if pos > m.start():
            def_line_idx = i
            break

    # find first body line
    j = def_line_idx + 1
    while j < len(lines) and lines[j].strip() == "":
        j += 1
    if j >= len(lines):
        return txt

    body_indent = indent_of(lines[j])
    indent = " " * body_indent

    # if first statement is a docstring, insert after docstring end
    if lines[j].lstrip().startswith(('"""', "'''")):
        quote = '"""' if lines[j].lstrip().startswith('"""') else "'''"
        j += 1
        while j < len(lines):
            if quote in lines[j]:
                j += 1
                break
            j += 1
        while j < len(lines) and lines[j].strip() == "":
            j += 1

    inject = indent + inject_line.rstrip() + "\n"
    # avoid double-inject
    if inject_line.strip() in "".join(lines[def_line_idx:def_line_idx+30]):
        return txt

    lines.insert(j, inject)
    return "".join(lines)

def main() -> None:
    if not CACHE.exists():
        raise SystemExit(f"cache.py not found: {CACHE}")

    txt = CACHE.read_text(encoding="utf-8", errors="ignore")
    bak = CACHE.with_suffix(f".py.bak.{ts()}")
    shutil.copy2(CACHE, bak)

    txt2 = txt
    txt2 = patch_func(
        txt2,
        "_cache_get_plan",
        "from .runner import _db_fetchrow, _ensure_json_obj",
    )
    txt2 = patch_func(
        txt2,
        "_cache_upsert_plan",
        "from .runner import _db_fetchval",
    )

    CACHE.write_text(txt2, encoding="utf-8")
    print("✅ Patched cache.py (lazy imports added)")
    print(f"- Backup: {bak}")

if __name__ == "__main__":
    main()
