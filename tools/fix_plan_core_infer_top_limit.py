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


def find_def_block(text: str, name: str) -> str | None:
    lines = text.splitlines(keepends=True)
    pat = re.compile(rf"^\s*def\s+{re.escape(name)}\s*\(")
    start = -1
    for i, ln in enumerate(lines):
        if pat.match(ln):
            start = i
            break
    if start == -1:
        return None

    base_indent = indent_of(lines[start])
    i = start + 1
    next_pat = re.compile(r"^\s*(def|async\s+def|class)\s+\w+")
    while i < len(lines):
        ln = lines[i]
        if next_pat.match(ln) and indent_of(ln) <= base_indent:
            end = i
            return "".join(lines[start:end]).rstrip() + "\n"
        i += 1
    return "".join(lines[start:]).rstrip() + "\n"


def ensure_import(plan_txt: str, import_line: str) -> str:
    if import_line.strip() in plan_txt:
        return plan_txt
    lines = plan_txt.splitlines(keepends=True)
    # insert after __future__ and existing imports block
    insert_at = 0
    for i, ln in enumerate(lines):
        if ln.startswith("import ") or ln.startswith("from "):
            insert_at = i + 1
    lines.insert(insert_at, import_line if import_line.endswith("\n") else import_line + "\n")
    return "".join(lines)


def insert_before(plan_txt: str, marker_regex: str, block: str) -> str:
    m = re.search(marker_regex, plan_txt, flags=re.MULTILINE)
    if not m:
        return plan_txt + "\n\n" + block
    idx = m.start()
    return plan_txt[:idx] + block + "\n" + plan_txt[idx:]


def main() -> None:
    if not RUNNER.exists():
        raise SystemExit(f"runner not found: {RUNNER}")
    if not PLAN.exists():
        raise SystemExit(f"plan_core not found: {PLAN}")

    runner_txt = RUNNER.read_text(encoding="utf-8", errors="ignore")
    plan_txt = PLAN.read_text(encoding="utf-8", errors="ignore")

    # if already exists in plan_core, do nothing
    if re.search(r"(?m)^\s*def\s+_infer_top_limit\s*\(", plan_txt):
        print("✅ plan_core.py already contains _infer_top_limit. Nothing to do.")
        return

    block = find_def_block(runner_txt, "_infer_top_limit")

    # fallback if not found
    if block is None:
        block = (
            "def _infer_top_limit(question: str) -> int | None:\n"
            "    \"\"\"Infer Top-N limit from Arabic/English question. Returns int or None.\"\"\"\n"
            "    if not question:\n"
            "        return None\n"
            "    q = str(question)\n"
            "    ql = q.lower()\n"
            "    # common patterns: أعلى 5 / top 10 / first 20\n"
            "    m = re.search(r\"(?:أعلى|افضل|أفضل|top|first)\\s*(\\d{1,4})\", ql)\n"
            "    if not m:\n"
            "        m = re.search(r\"\\btop\\s*(\\d{1,4})\\b\", ql)\n"
            "    if not m:\n"
            "        return None\n"
            "    try:\n"
            "        n = int(m.group(1))\n"
            "        return max(1, min(5000, n))\n"
            "    except Exception:\n"
            "        return None\n"
        )

    plan_bak = PLAN.with_suffix(f".py.bak.{ts()}")
    shutil.copy2(PLAN, plan_bak)

    plan_txt = ensure_import(plan_txt, "import re")
    plan_txt = insert_before(plan_txt, r"(?m)^\s*def\s+_rule_based_plan\s*\(", "\n" + block)

    PLAN.write_text(plan_txt, encoding="utf-8")

    print("✅ Added _infer_top_limit to plan_core.py")
    print(f"- Backup: {plan_bak}")


if __name__ == "__main__":
    main()
