from __future__ import annotations

import re
import shutil
from datetime import datetime
from pathlib import Path

RUNNER = Path("backend/app/services/ask/runner.py")
PLAN_CORE = Path("backend/app/services/ask/plan_core.py")


def ts() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def ensure_import_re(text: str) -> str:
    if re.search(r"(?m)^\s*import\s+re\s*$", text):
        return text
    # add re after future import if present, else at top
    m = re.search(r"(?m)^(from\s+__future__\s+import\s+[^\n]+\n)", text)
    if m:
        idx = m.end()
        return text[:idx] + "import re\n" + text[idx:]
    return "import re\n" + text


def upsert_plan_core_block(plan_core: str, block: str, marker_regex: str) -> str:
    """Append block only if marker not found."""
    if re.search(marker_regex, plan_core, flags=re.M):
        return plan_core
    if not plan_core.endswith("\n"):
        plan_core += "\n"
    return plan_core + "\n" + block.rstrip() + "\n"


def patch_plan_core_imports(plan_core: str) -> str:
    # ensure re exists (needed by _infer_top_limit)
    plan_core = ensure_import_re(plan_core)
    return plan_core


def extract_block(text: str, start_pat: str, end_pat: str | None = None) -> tuple[str | None, str]:
    """
    Extract block starting at start_pat (regex with MULTILINE),
    ending either at end_pat (if provided) or next top-level def/class (same indent).
    Returns (block, new_text_without_block).
    """
    m = re.search(start_pat, text, flags=re.M)
    if not m:
        return None, text
    start = m.start()

    if end_pat:
        m2 = re.search(end_pat, text[m.end():], flags=re.M)
        if not m2:
            raise SystemExit(f"Found start but not end for pattern: {start_pat}")
        end = m.end() + m2.start()
    else:
        # end at next top-level "def " starting at column 0 (or end of file)
        m2 = re.search(r"(?m)^(def|class)\s+\w+\s*\(", text[m.end():])
        end = len(text) if not m2 else (m.end() + m2.start())

    block = text[start:end].rstrip() + "\n"
    new_text = (text[:start] + text[end:]).lstrip("\n")
    return block, new_text


def ensure_runner_imports_infer(runner_txt: str) -> str:
    # Ensure runner imports _infer_top_limit from plan_core
    # Looks for "from .plan_core import ..." (single-line or parenthesized)
    m = re.search(r"(?m)^from\s+\.plan_core\s+import\s+(.+)$", runner_txt)
    if m and "(" not in m.group(0):
        line = m.group(0)
        if "_infer_top_limit" in line:
            return runner_txt
        new_line = line.rstrip() + ", _infer_top_limit"
        return runner_txt.replace(line, new_line, 1)

    # Parenthesized import block
    m = re.search(r"(?ms)^from\s+\.plan_core\s+import\s*\(\s*.*?\)\s*$", runner_txt)
    if not m:
        # If not found at all, add near top after imports
        ins = "\nfrom .plan_core import _infer_top_limit\n"
        return runner_txt + ins

    block = m.group(0)
    if "_infer_top_limit" in block:
        return runner_txt

    # Insert before closing ')'
    new_block = re.sub(r"\)\s*$", "    _infer_top_limit,\n)\n", block)
    return runner_txt.replace(block, new_block, 1)


def main() -> None:
    if not RUNNER.exists():
        raise SystemExit(f"Missing: {RUNNER}")
    if not PLAN_CORE.exists():
        raise SystemExit(f"Missing: {PLAN_CORE}")

    runner_txt = RUNNER.read_text(encoding="utf-8", errors="ignore")
    plan_core_txt = PLAN_CORE.read_text(encoding="utf-8", errors="ignore")

    bak_runner = RUNNER.with_suffix(f".py.bak.{ts()}")
    bak_core = PLAN_CORE.with_suffix(f".py.bak.{ts()}")
    shutil.copy2(RUNNER, bak_runner)
    shutil.copy2(PLAN_CORE, bak_core)

    # 1) Extract _TOP_HINTS from runner (your inserted block)
    top_hints_block, runner_txt2 = extract_block(
        runner_txt,
        start_pat=r"(?m)^\s*_TOP_HINTS\s*=\s*\(",
        end_pat=r"(?m)^\s*\)\s*$",
    )

    # 2) Extract def _infer_top_limit from runner
    infer_block, runner_txt3 = extract_block(
        runner_txt2,
        start_pat=r"(?m)^def\s+_infer_top_limit\s*\(",
        end_pat=None,
    )

    # If blocks not found, do nothing but still ensure plan_core has them
    # (plan_core might already contain them)
    plan_core_txt = patch_plan_core_imports(plan_core_txt)

    if top_hints_block:
        plan_core_txt = upsert_plan_core_block(
            plan_core_txt,
            top_hints_block,
            marker_regex=r"^\s*_TOP_HINTS\s*=",
        )

    if infer_block:
        plan_core_txt = upsert_plan_core_block(
            plan_core_txt,
            infer_block,
            marker_regex=r"^def\s+_infer_top_limit\s*\(",
        )

    # 3) Ensure runner imports _infer_top_limit from plan_core
    runner_txt_final = ensure_runner_imports_infer(runner_txt3)

    RUNNER.write_text(runner_txt_final, encoding="utf-8")
    PLAN_CORE.write_text(plan_core_txt, encoding="utf-8")

    print("✅ Move complete: _TOP_HINTS + _infer_top_limit -> plan_core.py")
    print(f"- runner backup   : {bak_runner}")
    print(f"- plan_core backup: {bak_core}")
    print("Next: compile + test.")


if __name__ == "__main__":
    main()
