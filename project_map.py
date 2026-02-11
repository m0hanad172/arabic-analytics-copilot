from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(".").resolve()

IGNORE_DIRS = {
    ".git", ".venv", "venv", "__pycache__", "node_modules",
    ".pytest_cache", ".mypy_cache", "dist", "build", ".ruff_cache"
}

EXT_OK = {".py", ".md", ".txt", ".yml", ".yaml", ".json", ".env", ".toml", ".ini"}

CATEGORIES = {
    "ASK_ENDPOINT": [
        r'@router\.(post|get)\(\s*["\']/ask',
        r'"/ask\??',
        r'ask_version',
        r'use_llm',
        r'use_cache',
    ],
    "PLANNER_PLAN": [
        r'\bplan\b\s*=?\s*{',
        r'"metrics"\s*:',
        r'"dimensions"\s*:',
        r'"filters"\s*:',
        r'"sort"\s*:',
        r'"limit"\s*:',
        r'rule_based',
        r'Planner',
        r'generate_plan',
        r'build_plan',
    ],
    "SEMANTIC_CATALOG": [
        r'\bsemantic\b',
        r'\bcatalog\b',
        r'\bmetrics?\b',
        r'\bdimensions?\b',
        r'alias',
        r'order_quarter',
        r'discount_amount',
    ],
    "LLM_GEMINI": [
        r'LLM_ENABLED',
        r'GEMINI_API_KEY',
        r'GOOGLE_API_KEY',
        r'GEMINI_MODEL',
        r'from google import genai',
        r'genai\.Client',
        r'gemini',
    ],
    "SQL_GUARDRAILS": [
        r'sql_guardrails',
        r'guardrails',
        r'block',
        r'multi[-_ ]statement',
    ],
    "SETTINGS_ENV": [
        r'load_dotenv',
        r'BaseSettings',
        r'pydantic_settings',
        r'env_file',
        r'\.env',
    ],
}

def iter_files(root: Path):
    for p in root.rglob("*"):
        if any(part in IGNORE_DIRS for part in p.parts):
            continue
        if p.is_file():
            if p.suffix in EXT_OK or p.name in {".env"}:
                # skip huge files
                try:
                    if p.stat().st_size > 2_000_000:
                        continue
                except Exception:
                    pass
                yield p

def read_text(p: Path) -> str | None:
    try:
        return p.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None

def main():
    hits = {k: [] for k in CATEGORIES.keys()}

    files = list(iter_files(ROOT))
    for f in files:
        txt = read_text(f)
        if not txt:
            continue

        for cat, patterns in CATEGORIES.items():
            for pat in patterns:
                if re.search(pat, txt, flags=re.IGNORECASE):
                    hits[cat].append(f)
                    break

    print("\n=== Project Map (likely file locations) ===")
    print(f"Root: {ROOT}")
    print(f"Scanned files: {len(files)} (<=2MB, ignoring {sorted(IGNORE_DIRS)})\n")

    for cat, fs in hits.items():
        fs = sorted(set(fs))
        print(f"[{cat}] hits: {len(fs)}")
        for f in fs[:30]:
            rel = f.relative_to(ROOT)
            print(f"  - {rel}")
        if len(fs) > 30:
            print(f"  ... (+{len(fs)-30} more)")
        print()

    print("=== Done ===")
    print("Tip: Send me the output + (optional) the top 3 files under ASK_ENDPOINT/PLANNER_PLAN/SEMANTIC_CATALOG.\n")

if __name__ == "__main__":
    main()
