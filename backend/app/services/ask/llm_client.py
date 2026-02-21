from __future__ import annotations

import os
import time
import random
import asyncio
import json
from dataclasses import dataclass
from typing import Any, Optional, Dict

from pathlib import Path
from dotenv import load_dotenv

# Force .env to win over stale PowerShell env vars
_ENV_PATH = Path(__file__).resolve().parents[3] / ".env"  # backend/.env
load_dotenv(_ENV_PATH, override=True)

# Optional Gemini SDK import (always define names)
genai = None
types = None
try:
    from google import genai as _genai  # type: ignore
    genai = _genai
    from google.genai import types as _types  # type: ignore
    types = _types
except Exception:
    genai = None
    types = None


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


# --- Config ---
GEMINI_API_KEY = (os.getenv("GEMINI_API_KEY") or "").strip()
GEMINI_MODEL = (os.getenv("GEMINI_MODEL", "models/gemini-2.5-flash") or "").strip()
GEMINI_API_VERSION = (os.getenv("GEMINI_API_VERSION", "v1beta") or "").strip()

LLM_BUDGET_SECONDS = _env_int("LLM_TIMEOUT_SECONDS", 12)
LLM_MAX_ATTEMPTS = _env_int("LLM_MAX_ATTEMPTS", 1)

LLM_CONCURRENCY = _env_int("LLM_CONCURRENCY", 1)
_LLM_SEM = asyncio.Semaphore(LLM_CONCURRENCY)

LLM_MAX_OUTPUT_TOKENS = _env_int("LLM_MAX_OUTPUT_TOKENS", 256)
LLM_TEMPERATURE = _env_float("LLM_TEMPERATURE", 0.0)

LLM_RETRY_SLEEP_MIN_MS = _env_int("LLM_RETRY_SLEEP_MIN_MS", 200)
LLM_RETRY_SLEEP_MAX_MS = _env_int("LLM_RETRY_SLEEP_MAX_MS", 700)

_CLIENT: Optional[Any] = None

PLAN_SCHEMA = {
  "type": "object",
  "required": ["metrics", "dimensions", "filters", "sort", "limit", "notes"],
  "properties": {
    "metrics": {"type": "array", "items": {"type": "string"}},
    "dimensions": {"type": "array", "items": {"type": "string"}},
    "filters": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["field", "op", "value"],
        "properties": {
          "field": {"type": "string"},
          "op": {"type": "string"},
          "value": {
            "type": ["string", "number", "integer", "boolean", "null", "array"],
            "items": {"type": ["string", "number", "integer", "boolean", "null"]},
          },
        },
      },
    },
    "sort": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["field", "dir"],
        "properties": {
          "field": {"type": "string"},
          "dir": {"type": "string", "enum": ["asc", "desc"]},
        },
      },
    },
    "limit": {"type": "integer"},
    "notes": {"type": "string"},
  },
}

def llm_enabled() -> bool:
    return bool(GEMINI_API_KEY) and (genai is not None)


def get_gemini_client() -> Optional[Any]:
    global _CLIENT
    if _CLIENT is not None:
        return _CLIENT

    if not llm_enabled():
        return None

    try:
        if hasattr(genai, "Client"):
            if types is not None:
                _CLIENT = genai.Client(
                    api_key=GEMINI_API_KEY,
                    http_options=types.HttpOptions(api_version=GEMINI_API_VERSION),
                )
            else:
                _CLIENT = genai.Client(api_key=GEMINI_API_KEY)
            return _CLIENT
    except Exception:
        _CLIENT = None
        return None

    return None


def _resp_all_text(resp: Any) -> str:
    """
    ✅ Robustly get ALL text (some responses are split into parts).
    """
    chunks = []

    t = getattr(resp, "text", None)
    if t and str(t).strip():
        chunks.append(str(t))

    cands = getattr(resp, "candidates", None)
    if cands:
        for cand in cands:
            content = getattr(cand, "content", None)
            parts = getattr(content, "parts", None) if content else None
            if not parts:
                continue
            for p in parts:
                pt = getattr(p, "text", None)
                if pt and str(pt).strip():
                    chunks.append(str(pt))

    out = "\n".join([c.strip() for c in chunks if c and c.strip()]).strip()
    return out


def _gemini_generate_sync(client: Any, prompt: str) -> str:
    cfg = {
        "temperature": LLM_TEMPERATURE,
        "max_output_tokens": LLM_MAX_OUTPUT_TOKENS,
        "response_mime_type": "application/json",
        "response_json_schema": PLAN_SCHEMA,
    }

    resp = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config=cfg,
    )

    # IMPORTANT: use response.text (structured output should be pure JSON)
    return (getattr(resp, "text", None) or "").strip()

async def call_gemini_with_budget(client: Any, prompt: str) -> LLMResult:
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
                return LLMResult(status="timeout", text="", ms=ms, attempts=attempts - 1, error=last_err or "budget exhausted")

            try:
                text = await asyncio.wait_for(
                    asyncio.to_thread(_gemini_generate_sync, client, prompt),
                    timeout=remaining,
                )
                ms = int((time.monotonic() - t0) * 1000)

                if text and text.strip():
                    return LLMResult(status="ok", text=text.strip(), ms=ms, attempts=attempts)

                last_err = "empty response text"

            except asyncio.TimeoutError:
                ms = int((time.monotonic() - t0) * 1000)
                last_err = f"timeout within remaining={remaining:.2f}s"
                return LLMResult(status="timeout", text="", ms=ms, attempts=attempts, error=last_err)

            except Exception as e:
                msg = str(e)
                ms = int((time.monotonic() - t0) * 1000)
                last_err = f"{type(e).__name__}: {msg[:220]}"
                if is_quota_error(msg):
                    return LLMResult(status="quota", text="", ms=ms, attempts=attempts, error=last_err)

                if attempts < max_attempts:
                    sleep_ms = random.randint(LLM_RETRY_SLEEP_MIN_MS, LLM_RETRY_SLEEP_MAX_MS)
                    await asyncio.sleep(min(0.6, sleep_ms / 1000.0))

        ms = int((time.monotonic() - t0) * 1000)
        return LLMResult(status="error", text="", ms=ms, attempts=attempts, error=last_err or "failed")
