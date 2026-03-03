from __future__ import annotations

import re
import shutil
from datetime import datetime
from pathlib import Path

RUNNER = Path("backend/app/services/ask/runner.py")
PLAN = Path("backend/app/services/ask/plan_core.py")


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


def find_assignment_line(lines: list[str], name: str) -> str | None:
    pat = re.compile(rf"^\s*{re.escape(name)}\s*=")
    for ln in lines:
        if pat.match(ln):
            return ln.rstrip("\n")
    return None


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

    targets = ["_normalize_plan", "_validate_plan", "_rule_based_plan"]
    missing = [t for t in targets if find_def_line(lines, t) == -1]
    if missing:
        raise SystemExit(f"ERROR: missing defs in runner.py: {missing}")

    runner_bak = RUNNER.with_suffix(f".py.bak.{ts()}")
    shutil.copy2(RUNNER, runner_bak)

    blocks: list[str] = []
    remove_ranges: list[tuple[int, int]] = []

    for name in targets:
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
    new_runner_txt = "".join(new_lines)

    # runner imports plan_core
    import_line = "from .plan_core import _normalize_plan, _validate_plan, _rule_based_plan\n"
    new_runner_txt = insert_import_after_imports(new_runner_txt, import_line)

    # create plan_core.py with safe helpers + keep runner constants if found
    PLAN.parent.mkdir(parents=True, exist_ok=True)
    if PLAN.exists():
        plan_bak = PLAN.with_suffix(f".py.bak.{ts()}")
        shutil.copy2(PLAN, plan_bak)

    # pull exact assignment lines if present
    default_max = find_assignment_line([ln.rstrip("\n") for ln in lines], "DEFAULT_MAX_ROWS")
    arab_map = find_assignment_line([ln.rstrip("\n") for ln in lines], "_ARABIC_DIGIT_MAP")

    header = """from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Set

from fastapi import HTTPException

# Extracted from services/ask/runner.py (Step3A)
# Goal: keep runner smaller with no behavior change.

def _catalog_keys(catalog: dict, key: str) -> Set[str]:
    \"\"\"Return allowed keys from catalog lists (supports list[str] or list[dict]).\"\"\"
    items = catalog.get(key) or []
    out: Set[str] = set()
    if isinstance(items, list):
        for it in items:
            if isinstance(it, str):
                k = it.strip()
                if k:
                    out.add(k)
            elif isinstance(it, dict):
                k = it.get("key") or it.get("name") or it.get("metric_key") or it.get("dim_key")
                if k:
                    out.add(str(k).strip())
    return out

"""

    # Provide constants (prefer exact runner lines if available)
    consts = []
    if default_max:
        consts.append(default_max)
    else:
        # fallback: keep same clamp behavior; default 5000 is a safe default in this project
        consts.append('DEFAULT_MAX_ROWS = int(os.getenv("DEFAULT_MAX_ROWS", "5000"))')

    if arab_map:
        consts.append(arab_map)
    else:
        # fallback mapping for Arabic-Indic + Eastern Arabic digits
        consts.append('_ARABIC_DIGIT_MAP = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")')

    plan_txt = header + "\n".join(consts).rstrip() + "\n\n" + "\n".join(blocks).rstrip() + "\n"

    PLAN.write_text(plan_txt, encoding="utf-8")
    RUNNER.write_text(new_runner_txt, encoding="utf-8")

    print("✅ Step3A complete: plan core extracted")
    print(f"- runner backup: {runner_bak}")
    print(f"- updated: {PLAN}")
    print("- runner.py updated to import plan core helpers")
    print("\nRestart server and test /ask + cache.\n")


if __name__ == "__main__":
    main()
