from __future__ import annotations

import re
import shutil
from datetime import datetime
from pathlib import Path

RUNNER = Path("backend/app/services/ask/runner.py")
CATALOG = Path("backend/app/services/ask/catalog.py")


def ts() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def indent_of(line: str) -> int:
    # count leading spaces/tabs safely
    return len(line) - len(line.lstrip(" \t"))


def find_def_line(lines: list[str], name: str) -> int:
    pat = re.compile(rf"^\s*(async\s+def|def)\s+{re.escape(name)}\s*\(")
    for i, ln in enumerate(lines):
        if pat.match(ln):
            return i
    return -1


def include_decorators(lines: list[str], def_i: int) -> int:
    """Walk upwards to include decorator lines directly above the def (same indentation)."""
    base_indent = indent_of(lines[def_i])
    i = def_i - 1
    while i >= 0:
        ln = lines[i]
        if ln.lstrip().startswith("@") and indent_of(ln) == base_indent:
            i -= 1
            continue
        break
    return i + 1


def find_block_end(lines: list[str], start_i: int) -> int:
    """Return end index (exclusive) of a top-level function/class block."""
    base_indent = indent_of(lines[start_i])
    i = start_i + 1
    pat = re.compile(r"^\s*(async\s+def|def|class)\s+\w+")
    while i < len(lines):
        ln = lines[i]
        # new top-level block (same or less indent) ends the current block
        if pat.match(ln) and indent_of(ln) <= base_indent:
            return i
        # decorator at same or less indent also indicates next block starts soon
        if ln.lstrip().startswith("@") and indent_of(ln) <= base_indent:
            return i
        i += 1
    return len(lines)


def insert_import_after_imports(py_text: str, import_line: str) -> str:
    if import_line.strip() in py_text:
        return py_text
    lines = py_text.splitlines(keepends=True)

    i = 0
    # shebang/comments/encoding
    while i < len(lines) and (lines[i].startswith("#!") or lines[i].startswith("# -*-") or lines[i].strip().startswith("#")):
        i += 1

    # module docstring
    if i < len(lines) and lines[i].lstrip().startswith(('"""', "'''")):
        q = '"""' if lines[i].lstrip().startswith('"""') else "'''"
        i += 1
        while i < len(lines):
            if q in lines[i]:
                i += 1
                break
            i += 1

    # imports block
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
        raise SystemExit(f"ERROR: runner not found: {RUNNER}")

    # read with utf-8-sig to survive BOM if present
    runner_txt = RUNNER.read_text(encoding="utf-8-sig", errors="ignore")
    lines = runner_txt.splitlines(keepends=True)

    runner_bak = RUNNER.with_suffix(f".py.bak.{ts()}")
    shutil.copy2(RUNNER, runner_bak)

    # Find target functions (we prioritize _augment_catalog; _ensure_key is optional)
    idx_aug = find_def_line(lines, "_augment_catalog")
    if idx_aug == -1:
        raise SystemExit("ERROR: _augment_catalog not found in runner.py (cannot do Step1 safely)")

    idx_ens = find_def_line(lines, "_ensure_key")  # may be -1

    # Build extraction plan: extract _ensure_key first if it appears before augment
    targets: list[tuple[str, int]] = []
    if idx_ens != -1 and idx_ens < idx_aug:
        targets.append(("_ensure_key", idx_ens))
    targets.append(("_augment_catalog", idx_aug))

    extracted_blocks: list[str] = []
    remove_ranges: list[tuple[int, int]] = []

    for name, def_i in targets:
        # locate again because indices shift only if we mutate; we haven't mutated yet
        def_i = find_def_line(lines, name)
        if def_i == -1:
            continue
        start_i = include_decorators(lines, def_i)
        end_i = find_block_end(lines, def_i)
        extracted_blocks.append("".join(lines[start_i:end_i]).rstrip() + "\n")
        remove_ranges.append((start_i, end_i))

    # Merge overlapping ranges safely (from end to start)
    remove_ranges = sorted(remove_ranges, key=lambda x: (x[0], x[1]))
    merged: list[tuple[int, int]] = []
    for a, b in remove_ranges:
        if not merged or a > merged[-1][1]:
            merged.append((a, b))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))

    # Remove blocks from runner (delete from bottom to top)
    new_lines = lines[:]
    for a, b in reversed(merged):
        del new_lines[a:b]

    new_runner_txt = "".join(new_lines)
    new_runner_txt = insert_import_after_imports(
        new_runner_txt,
        "from .catalog import _augment_catalog" + (", _ensure_key" if idx_ens != -1 else "") + "\n",
    )

    # Write catalog.py
    CATALOG.parent.mkdir(parents=True, exist_ok=True)
    if CATALOG.exists():
        cat_bak = CATALOG.with_suffix(f".py.bak.{ts()}")
        shutil.copy2(CATALOG, cat_bak)

    header = """from __future__ import annotations

# Extracted from services/ask/runner.py (Step1)
# Goal: keep runner.py smaller with no behavior change.

"""
    CATALOG.write_text(header + "\n".join(extracted_blocks).rstrip() + "\n", encoding="utf-8")

    # Write runner
    RUNNER.write_text(new_runner_txt, encoding="utf-8")

    print("✅ Step1 v3 complete")
    print(f"- runner backup: {runner_bak}")
    print(f"- updated: {CATALOG}")
    print("- runner.py updated to import extracted helpers")
    print("\nRestart server and test /ask.\n")


if __name__ == "__main__":
    main()
