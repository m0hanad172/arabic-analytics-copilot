from __future__ import annotations

import re
import shutil
from datetime import datetime
from pathlib import Path

CACHE = Path("backend/app/services/ask/cache.py")
RUNNER = Path("backend/app/services/ask/runner.py")

def ts() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")

def backup(p: Path) -> Path:
    b = p.with_suffix(p.suffix + f".bak.{ts()}")
    shutil.copy2(p, b)
    return b

def main() -> None:
    if not CACHE.exists():
        raise SystemExit(f"cache not found: {CACHE}")
    if not RUNNER.exists():
        raise SystemExit(f"runner not found: {RUNNER}")

    cache_txt = CACHE.read_text(encoding="utf-8", errors="ignore")
    runner_txt = RUNNER.read_text(encoding="utf-8", errors="ignore")

    cache_bak = backup(CACHE)
    runner_bak = backup(RUNNER)

    # 1) Remove any bad module-level imports from runner (circular)
    cache_txt = re.sub(r"(?m)^\s*from\s+\.runner\s+import\s+.*\n", "", cache_txt)

    # 2) Update cache function signatures to accept deps
    # _cache_get_plan(question_norm, catalog_hash) -> add db_fetchrow, ensure_json_obj
    cache_txt, n1 = re.subn(
        r"(async\s+def\s+_cache_get_plan\s*\(\s*question_norm\s*:\s*[^,]+,\s*catalog_hash\s*:\s*[^)\n]+)(\)\s*->)",
        r"\1, db_fetchrow, ensure_json_obj\2",
        cache_txt,
        flags=re.MULTILINE,
    )

    # _cache_upsert_plan(question_norm, question_raw, catalog_hash, plan, model) -> add db_fetchval
    cache_txt, n2 = re.subn(
        r"(async\s+def\s+_cache_upsert_plan\s*\(\s*question_norm\s*:\s*[^,]+,\s*question_raw\s*:\s*[^,]+,\s*catalog_hash\s*:\s*[^,]+,\s*plan\s*:\s*[^,]+,\s*model\s*:\s*[^)\n]+)(\)\s*->)",
        r"\1, db_fetchval\2",
        cache_txt,
        flags=re.MULTILINE,
    )

    # 3) Replace internal calls to runner helpers with injected deps
    cache_txt = cache_txt.replace("_db_fetchrow(", "db_fetchrow(")
    cache_txt = cache_txt.replace("_ensure_json_obj(", "ensure_json_obj(")
    cache_txt = cache_txt.replace("_db_fetchval(", "db_fetchval(")

    # 4) Patch runner call-sites (very specific, safe replacements)
    # cached = await _cache_get_plan(q_norm, c_hash)
    runner_txt, r1 = re.subn(
        r"await\s+_cache_get_plan\(\s*q_norm\s*,\s*c_hash\s*\)",
        r"await _cache_get_plan(q_norm, c_hash, _db_fetchrow, _ensure_json_obj)",
        runner_txt,
    )

    # await _cache_upsert_plan(q_norm, body.question, c_hash, plan, model_name)
    runner_txt, r2 = re.subn(
        r"await\s+_cache_upsert_plan\(\s*q_norm\s*,\s*body\.question\s*,\s*c_hash\s*,\s*plan\s*,\s*model_name\s*\)",
        r"await _cache_upsert_plan(q_norm, body.question, c_hash, plan, model_name, _db_fetchval)",
        runner_txt,
    )

    # If patterns didn't match (code slightly different), do a softer patch:
    if r1 == 0:
        # try cached variable name or whitespace variants
        runner_txt = re.sub(
            r"await\s+_cache_get_plan\(\s*([a-zA-Z_]\w*)\s*,\s*([a-zA-Z_]\w*)\s*\)",
            r"await _cache_get_plan(\1, \2, _db_fetchrow, _ensure_json_obj)",
            runner_txt,
            count=1,
        )
    if r2 == 0:
        runner_txt = re.sub(
            r"await\s+_cache_upsert_plan\(\s*([a-zA-Z_]\w*)\s*,\s*([a-zA-Z_]\w*(?:\.\w+)*)\s*,\s*([a-zA-Z_]\w*)\s*,\s*plan\s*,\s*model_name\s*\)",
            r"await _cache_upsert_plan(\1, \2, \3, plan, model_name, _db_fetchval)",
            runner_txt,
            count=1,
        )

    # Write files
    CACHE.write_text(cache_txt, encoding="utf-8")
    RUNNER.write_text(runner_txt, encoding="utf-8")

    print("✅ Fixed circular import between runner.py and cache.py")
    print(f"- cache backup : {cache_bak}")
    print(f"- runner backup: {runner_bak}")
    print("\nNext: restart server and test use_cache=1.\n")

if __name__ == "__main__":
    main()
