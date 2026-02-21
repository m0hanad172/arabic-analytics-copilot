# backend/app/services/ask/llm_client.py
from __future__ import annotations

import os
import time
import random
import asyncio
from dataclasses import dataclass
from typing import Any, Optional

# Load .env early so env-based LLM settings (timeouts/model/key) are applied
# even when this module is imported before other dotenv loaders.
from pathlib import Path

try:
    from dotenv import load_dotenv
    _ENV_PATH = Path(__file__).resolve().parents[3] / '.env'  # backend/.env
    load_dotenv(_ENV_PATH, override=False)
except Exception:
    pass

# Optional Gemini SDK import
try:
    from google import genai  # type: ignore
except Exception:  # pragma: no cover
    genai = None


@dataclass
class LLMResult:
    status: str  # "ok" | "timeout" | "quota" | "error" | "disabled"
    text: str
    ms: int
    attempts: int
    error: str = ""


def is_quota_error(msg: str) -> bool:
    m = (msg or "").upper()
    return ("429" in m) or ("RESOURCE_EXHAUSTED" in m) or ("QUOTA" in m) or ("RATE LIMIT" in m)


def _env_int(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    try:
        n = int(raw)
        return n if n > 0 else default
    except Exception:
        return default


def _env_float(name: str, default: float) -> float:
    raw = (os.getenv(name) or "").strip()
    try:
        return float(raw)
    except Exception:
        return default


# --- Config (safe defaults) ---
GEMINI_API_KEY = (os.getenv("GEMINI_API_KEY") or "").strip()
GEMINI_MODEL = (os.getenv("GEMINI_MODEL", "gemini-3-flash-preview") or "").strip()

# Total time budget for the whole LLM attempt(s) (seconds)
LLM_BUDGET_SECONDS = _env_int("LLM_TIMEOUT_SECONDS", 12)

# Max attempts within budget (recommend 1; 2 only if you really want)
LLM_MAX_ATTEMPTS = _env_int("LLM_MAX_ATTEMPTS", 1)

# Concurrency limiter to prevent thread pile-up (very important)
LLM_CONCURRENCY = _env_int("LLM_CONCURRENCY", 1)
_LLM_SEM = asyncio.Semaphore(LLM_CONCURRENCY)

# Optional generation config to reduce latency
LLM_MAX_OUTPUT_TOKENS = _env_int("LLM_MAX_OUTPUT_TOKENS", 600)
LLM_TEMPERATURE = _env_float("LLM_TEMPERATURE", 0.0)

# Small retry sleeps (only if attempts>1 and budget allows)
LLM_RETRY_SLEEP_MIN_MS = _env_int("LLM_RETRY_SLEEP_MIN_MS", 200)
LLM_RETRY_SLEEP_MAX_MS = _env_int("LLM_RETRY_SLEEP_MAX_MS", 700)

# Cache the client (avoid re-init every request)
_CLIENT: Optional[Any] = None


def llm_enabled() -> bool:
    return bool(GEMINI_API_KEY) and genai is not None


def get_gemini_client() -> Optional[Any]:
    """Returns a cached ready client or None."""
    global _CLIENT
    if _CLIENT is not None:
        return _CLIENT
    if not llm_enabled():
        return None
    try:
        if hasattr(genai, "Client"):
            _CLIENT = genai.Client(api_key=GEMINI_API_KEY)
            return _CLIENT
    except Exception:
        _CLIENT = None
        return None
    return None


def _gemini_generate_sync(client: Any, prompt: str) -> str:
    """Blocking call executed in a thread."""
    # Some SDK versions accept a config object; keep it best-effort
    cfg = {"temperature": LLM_TEMPERATURE, "max_output_tokens": LLM_MAX_OUTPUT_TOKENS}
    try:
        resp = client.models.generate_content(model=GEMINI_MODEL, contents=prompt, config=cfg)
    except TypeError:
        resp = client.models.generate_content(model=GEMINI_MODEL, contents=prompt)

    return (getattr(resp, "text", None) or "").strip()


async def call_gemini_with_budget(client: Any, prompt: str) -> LLMResult:
    """
    Runs Gemini with:
      - total budget (LLM_BUDGET_SECONDS)
      - max attempts (LLM_MAX_ATTEMPTS)
      - concurrency guard (LLM_CONCURRENCY)
    Returns LLMResult with status + timing.
    """
    if client is None:
        return LLMResult(status="disabled", text="", ms=0, attempts=0, error="client is None")

    t0 = time.monotonic()
    attempts = 0
    last_err = ""

    async with _LLM_SEM:
        max_attempts = max(1, int(LLM_MAX_ATTEMPTS))

        while attempts < max_attempts:
            attempts += 1

            elapsed = time.monotonic() - t0
            remaining = float(LLM_BUDGET_SECONDS) - elapsed
            if remaining <= 0:
                ms = int((time.monotonic() - t0) * 1000)
                # if last error indicates timeout, return timeout; else error
                if "timeout" in (last_err or "").lower():
                    return LLMResult(status="timeout", text="", ms=ms, attempts=attempts - 1, error=last_err or "budget exhausted")
                return LLMResult(status="error", text="", ms=ms, attempts=attempts - 1, error=last_err or "budget exhausted")

            try:
                text = await asyncio.wait_for(
                    asyncio.to_thread(_gemini_generate_sync, client, prompt),
                    timeout=remaining,
                )
                ms = int((time.monotonic() - t0) * 1000)

                if text:
                    return LLMResult(status="ok", text=text, ms=ms, attempts=attempts)

                last_err = "empty response text"

                # if we will retry, do a tiny jitter sleep (only if budget allows)
                if attempts < max_attempts:
                    elapsed2 = time.monotonic() - t0
                    remaining2 = float(LLM_BUDGET_SECONDS) - elapsed2
                    if remaining2 > 0.6:
                        sleep_ms = random.randint(LLM_RETRY_SLEEP_MIN_MS, LLM_RETRY_SLEEP_MAX_MS)
                        sleep_s = min(remaining2 - 0.2, sleep_ms / 1000.0)
                        if sleep_s > 0:
                            await asyncio.sleep(sleep_s)

            except asyncio.TimeoutError:
                ms = int((time.monotonic() - t0) * 1000)
                last_err = f"timeout within remaining={remaining:.2f}s"
                # ✅ return timeout immediately (don’t waste budget on another try)
                return LLMResult(status="timeout", text="", ms=ms, attempts=attempts, error=last_err)

            except Exception as e:
                msg = str(e)
                ms = int((time.monotonic() - t0) * 1000)
                last_err = f"{type(e).__name__}: {msg[:220]}"

                if is_quota_error(msg):
                    return LLMResult(status="quota", text="", ms=ms, attempts=attempts, error=last_err)

                # transient: short sleep if we still have budget and will retry
                if attempts < max_attempts:
                    elapsed2 = time.monotonic() - t0
                    remaining2 = float(LLM_BUDGET_SECONDS) - elapsed2
                    if remaining2 > 0.6:
                        sleep_ms = random.randint(LLM_RETRY_SLEEP_MIN_MS, LLM_RETRY_SLEEP_MAX_MS)
                        sleep_s = min(remaining2 - 0.2, sleep_ms / 1000.0)
                        if sleep_s > 0:
                            await asyncio.sleep(sleep_s)

        ms = int((time.monotonic() - t0) * 1000)
        return LLMResult(status="error", text="", ms=ms, attempts=attempts, error=last_err or "failed")
