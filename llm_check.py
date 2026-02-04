#!/usr/bin/env python3
"""
Universal LLM/Gemini state check (env + optional env-file + import + optional ping).

Usage:
  python llm_check.py
  python llm_check.py --env-file backend/.env
  python llm_check.py --env-file backend/.env --ping
  python llm_check.py --env-file backend/.env --ping --model gemini-2.0-flash

Notes:
- Does NOT print API keys; only prints length and last4.
- Loads env file in this priority:
  1) --env-file if provided
  2) .env in current dir
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def parse_bool(x: str | None) -> bool:
    if x is None:
        return False
    return x.strip().lower() in {"1", "true", "yes", "y", "on"}


def mask_secret(s: str | None) -> str:
    if not s or not s.strip():
        return "missing"
    s = s.strip()
    if len(s) <= 8:
        return f"present(len={len(s)})"
    return f"present(len={len(s)}, last4={s[-4:]})"


def manual_load_env_file(path: Path) -> int:
    """
    Minimal .env parser (KEY=VALUE). Ignores comments and blank lines.
    Will not override existing environment variables.
    """
    if not path.exists():
        return 0

    loaded = 0
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")  # remove quotes if any
        if k and (k not in os.environ):  # don't override existing
            os.environ[k] = v
            loaded += 1
    return loaded


def load_env(path_str: str | None) -> str:
    # Try python-dotenv if installed; otherwise manual load.
    path = None
    if path_str:
        path = Path(path_str)
    else:
        path = Path.cwd() / ".env"

    if not path.exists():
        return f"env file not found: {path}"

    # Try python-dotenv
    try:
        from dotenv import load_dotenv  # type: ignore
        load_dotenv(path)
        return f"loaded via python-dotenv: {path}"
    except Exception:
        n = manual_load_env_file(path)
        return f"loaded via manual parser ({n} vars): {path}"


def check_google_genai_import() -> tuple[bool, str]:
    try:
        from google import genai  # noqa: F401
        # try read version
        try:
            from importlib.metadata import version
            ver = version("google-genai")
            return True, f"OK (google-genai {ver})"
        except Exception:
            return True, "OK (google-genai version unknown)"
    except Exception as e:
        return False, f"FAILED: {type(e).__name__}: {e}"


def ping_gemini(model: str) -> tuple[bool, str]:
    key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not key:
        return False, "No GEMINI_API_KEY or GOOGLE_API_KEY present."

    try:
        from google import genai
        client = genai.Client(api_key=key)
        resp = client.models.generate_content(
            model=model,
            contents="Reply with exactly: OK",
        )
        text = (getattr(resp, "text", "") or "").strip()
        return (text == "OK"), f"response={text!r}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env-file", default=None, help="Path to env file (e.g. backend/.env)")
    ap.add_argument("--ping", action="store_true", help="Actually call Gemini")
    ap.add_argument("--model", default=None, help="Gemini model name (overrides env GEMINI_MODEL)")
    args = ap.parse_args()

    env_status = load_env(args.env_file)

    llm_enabled_raw = os.getenv("LLM_ENABLED")
    llm_enabled = parse_bool(llm_enabled_raw)

    gemini_key = os.getenv("GEMINI_API_KEY")
    google_key = os.getenv("GOOGLE_API_KEY")

    model = args.model or os.getenv("GEMINI_MODEL") or "gemini-2.0-flash"

    import_ok, import_msg = check_google_genai_import()

    print("\n=== LLM/Gemini Check ===")
    print(f"cwd: {Path.cwd()}")
    print(f"env: {env_status}")
    print(f"LLM_ENABLED: {llm_enabled_raw!r} -> {llm_enabled}")
    print(f"GEMINI_MODEL: {model!r}")
    print(f"GEMINI_API_KEY: {mask_secret(gemini_key)}")
    print(f"GOOGLE_API_KEY: {mask_secret(google_key)}")
    print(f"google-genai import: {import_msg}")

    if not args.ping:
        print("ping: skipped (use --ping)\n")
        return 0

    if not llm_enabled:
        print("ping: blocked because LLM_ENABLED is false\n")
        return 2

    if not import_ok:
        print("ping: blocked because google-genai import failed\n")
        return 3

    ok, msg = ping_gemini(model)
    print(f"ping: ok={ok} | {msg}\n")
    return 0 if ok else 4


if __name__ == "__main__":
    raise SystemExit(main())
