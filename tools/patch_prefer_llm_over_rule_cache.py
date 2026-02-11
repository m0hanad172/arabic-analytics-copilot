from __future__ import annotations

import re
import shutil
from datetime import datetime
from pathlib import Path

RUNNER = Path("backend/app/services/ask/runner.py")


def ts() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def main() -> None:
    if not RUNNER.exists():
        raise SystemExit(f"runner not found: {RUNNER}")

    txt = RUNNER.read_text(encoding="utf-8", errors="ignore")

    # Avoid double patch
    if "prefer LLM over cached rule_based plan" in txt:
        print("✅ runner.py already patched. Nothing to do.")
        return

    bak = RUNNER.with_suffix(f".py.bak.{ts()}")
    shutil.copy2(RUNNER, bak)

    # Find the first 'used_cache = True' inside the cache block of ask()
    # and inject logic right after it.
    pat = r"(?m)^(?P<indent>\s*)used_cache\s*=\s*True\s*$"
    m = re.search(pat, txt)
    if not m:
        raise SystemExit("Could not find 'used_cache = True' in runner.py to patch safely.")

    indent = m.group("indent")
    inject = (
        f"\n"
        f"{indent}# prefer LLM over cached rule_based plan when explicitly requested\n"
        f"{indent}if use_llm and isinstance(plan, dict) and plan.get('notes') == 'rule_based':\n"
        f"{indent}    plan = None\n"
        f"{indent}    used_cache = False\n"
    )

    new_txt = txt[: m.end()] + inject + txt[m.end() :]

    RUNNER.write_text(new_txt, encoding="utf-8")

    print("✅ Patched runner.py: prefer LLM over cached rule_based plan when use_llm=1")
    print(f"- Backup: {bak}")


if __name__ == "__main__":
    main()
