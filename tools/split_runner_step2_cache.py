from __future__ import annotations

import re
import shutil
from datetime import datetime
from pathlib import Path

RUNNER = Path("backend/app/services/ask/runner.py")
CACHE = Path("backend/app/services/ask/cache.py")


def ts() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def indent_of(line: str) -> int:
    return len(line) - len(line.lstrip(" \t"))


def find_def_line(lines: list[str], name: str) -> int:
    pat = re.compile(rf"^\s*(async\s+def|def)\s+{re.escape(name)}\s*\(")
    for i, ln in enumerate(lines):
        if pat.match(ln):
            return i
    return -1


def include_decorators(lines: list[str], def_i: int) -> int:
    base_indent = indent_of(lines[def_i])
    i = def_i - 1
    while i >= 0:
        ln = lines[i]
        if ln.lstrip().startswith("@") and indent_of(ln) == base_indent:
            i -= 1
            continue
        break
    return i + 1


def find_block_end(lines: list[str], def_i: int) -> int:
    base_indent = indent_of(lines[def_i])
    i = def_i + 1
    pat = re.compile(r"^\s*(async\s+def|def|class)\s+\w+")
    while i < len(lines):
        ln = lines[i]
        if pat.match(ln) and indent_of(ln) <= base_indent:
            return i
        if ln.lstrip().startswith("@") and indent_of(ln) <= base_indent:
            return i
        i += 1
    return len(lines)


def insert_import_after_imports(py_text: str, import_line: str) -> str:
    if import_line.strip() in py_text:
        return py_text
    lines = py_text.splitlines(keepends=True)

    i = 0
    while i < len(lines) and (lines[i].startswith("#!") or lines[i].startswith("# -*-") or lines[i].strip().startswith("#")):
        i += 1

    if i < len(lines) and lines[i].lstrip().startswith(('"""', "'''")):
        q = '"""' if lines[i].lstrip().startswith('"""') else "'''"
        i += 1
        while i < len(lines):
            if q in lines[i]:
                i += 1
                break
            i += 1

    while i < len(lines):
        s = lines[i].strip()
        if not s or s.startswith("#") or s.startswith(("from ", "import ")):
            i += 1
            continue
        break

    lines.insert(i, import_line if import_line.endswith("\n") else import_line + "\n")
    return "".join(lines)


def main() -> None:
    if not RUNNER.exists():
        raise SystemExit(f"runner not found: {RUNNER}")

    txt = RUNNER.read_text(encoding="utf-8-sig", errors="ignore")
    lines = txt.splitlines(keepends=True)

    targets = ["_normalize_question", "_cache_get_plan", "_cache_upsert_plan"]

    # verify presence
    present = [t for t in targets if find_def_line(lines, t) != -1]
    if not present:
        raise SystemExit("ERROR: none of cache functions found in runner.py (names may differ)")

    runner_bak = RUNNER.with_suffix(f".py.bak.{ts()}")
    shutil.copy2(RUNNER, runner_bak)

    blocks: list[str] = []
    remove_ranges: list[tuple[int, int]] = []

    for name in present:
        def_i = find_def_line(lines, name)
        start_i = include_decorators(lines, def_i)
        end_i = find_block_end(lines, def_i)
        blocks.append("".join(lines[start_i:end_i]).rstrip() + "\n")
        remove_ranges.append((start_i, end_i))

    # merge ranges
    remove_ranges = sorted(remove_ranges)
    merged: list[tuple[int, int]] = []
    for a, b in remove_ranges:
        if not merged or a > merged[-1][1]:
            merged.append((a, b))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))

    # delete from bottom to top
    new_lines = lines[:]
    for a, b in reversed(merged):
        del new_lines[a:b]

    new_txt = "".join(new_lines)

    # write cache.py
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    if CACHE.exists():
        cache_bak = CACHE.with_suffix(f".py.bak.{ts()}")
        shutil.copy2(CACHE, cache_bak)

    header = """from __future__ import annotations

# Extracted from services/ask/runner.py (Step2)
# Cache helpers for bi_meta.plan_cache (no behavior change).

"""
    CACHE.write_text(header + "\n".join(blocks).rstrip() + "\n", encoding="utf-8")

    # add import in runner
    import_line = "from .cache import " + ", ".join(present) + "\n"
    new_txt = insert_import_after_imports(new_txt, import_line)

    RUNNER.write_text(new_txt, encoding="utf-8")

    print("✅ Step2 complete: cache functions extracted")
    print(f"- runner backup: {runner_bak}")
    print(f"- updated: {CACHE}")
    print("- runner.py updated to import cache helpers")
    print("\nRestart server and test /ask.\n")


if __name__ == "__main__":
    main()
