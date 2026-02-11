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

def main() -> None:
    if not RUNNER.exists():
        raise SystemExit(f"runner.py not found: {RUNNER}")

    src = RUNNER.read_text(encoding="utf-8")

    if "_get_gclient" in src:
        print("ℹ️ _get_gclient already exists (skipping insert).")
    else:
        # Find gclient declaration line (with or without type annotation)
        m = re.search(r"(?m)^\s*gclient\s*(?::[^\n=]+)?=\s*None\s*$", src)
        if not m:
            raise SystemExit("Could not find 'gclient = None' line in runner.py")

        insert_at = m.end()

        helper = """
def _get_gclient():
    \"\"\"Lazy-init Gemini client to avoid import-time failures / reload issues.\"\"\"
    global gclient
    if gclient is not None:
        return gclient
    try:
        # LLM_ENABLED already checks key presence + genai import, but keep it defensive
        if not LLM_ENABLED or genai is None or not GEMINI_API_KEY:
            return None
        gclient = genai.Client(api_key=GEMINI_API_KEY)
        return gclient
    except Exception:
        gclient = None
        return None

""".lstrip("\n")

        src = src[:insert_at] + "\n\n" + helper + src[insert_at:]

    # Replace only the LLM gate to use _get_gclient()
    # This keeps existing logic but ensures client is created when needed.
    if "and _get_gclient() is not None" not in src:
        src2 = re.sub(
            r"\band\s+gclient\s+is\s+not\s+None\b",
            "and _get_gclient() is not None",
            src,
        )
        src = src2

    b = backup(RUNNER)
    RUNNER.write_text(src, encoding="utf-8")

    print("✅ Patched runner.py: lazy-init gclient via _get_gclient()")
    print(f"- Backup: {b}")

if __name__ == "__main__":
    main()
