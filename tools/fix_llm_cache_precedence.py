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

def main():
    if not RUNNER.exists():
        raise SystemExit(f"runner.py not found: {RUNNER}")

    src = RUNNER.read_text(encoding="utf-8")

    # Find: <var> = await _cache_get_plan(
    m = re.search(r"(?m)^(\s*)(\w+)\s*=\s*await\s*_cache_get_plan\s*\(", src)
    if not m:
        raise SystemExit("Could not find 'await _cache_get_plan(' assignment in runner.py")

    indent = m.group(1)
    var = m.group(2)

    snippet = (
        f"{indent}# If cache returned a rule_based plan but caller requested LLM, ignore cache so LLM can run.\n"
        f"{indent}if use_llm and {var} and str({var}.get('notes','')).strip().lower() == 'rule_based':\n"
        f"{indent}    {var} = None\n"
        f"{indent}    used_cache = False\n"
    )

    # Don’t double-insert
    if "ignore cache so LLM can run" in src:
        print("ℹ️ Patch already present in runner.py (skipping).")
        return

    # Insert snippet right after the cache_get_plan line
    lines = src.splitlines(True)
    out = []
    inserted = False

    for i, line in enumerate(lines):
        out.append(line)
        if not inserted and re.match(r"^\s*\w+\s*=\s*await\s*_cache_get_plan\s*\(", line):
            out.append(snippet)
            inserted = True

    if not inserted:
        raise SystemExit("Failed to insert patch (unexpected).")

    b = backup(RUNNER)
    RUNNER.write_text("".join(out), encoding="utf-8")
    print("✅ Patched runner.py: LLM wins over cached rule_based when use_llm=1 & use_cache=1")
    print(f"- Backup: {b}")

if __name__ == "__main__":
    main()
