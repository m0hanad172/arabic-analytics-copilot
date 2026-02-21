import asyncio
import os
import time
from dataclasses import dataclass
from typing import Optional, Set, List

# Official Google GenAI SDK (google-genai)
try:
    from google import genai  # type: ignore
except Exception:  # pragma: no cover
    genai = None  # type: ignore

try:
    from google.genai import types as genai_types  # type: ignore
except Exception:  # pragma: no cover
    genai_types = None  # type: ignore


# -------------------------
# Config (env)
# -------------------------
LLM_TIMEOUT_SECONDS = float(os.getenv("LLM_TIMEOUT_SECONDS", "12"))
LLM_MAX_ATTEMPTS = int(os.getenv("LLM_MAX_ATTEMPTS", "2"))
LLM_BACKOFF_BASE_MS = int(os.getenv("LLM_BACKOFF_BASE_MS", "400"))
LLM_BACKOFF_MAX_MS = int(os.getenv("LLM_BACKOFF_MAX_MS", "1800"))

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

# Examples: v1, v1beta, v1alpha
GEMINI_API_VERSION = os.getenv("GEMINI_API_VERSION", "v1").strip() or "v1"

# Client timeout is in milliseconds (SDK HttpOptions)
GEMINI_HTTP_TIMEOUT_MS = int(
    os.getenv("GEMINI_HTTP_TIMEOUT_MS", str(int(max(1.0, LLM_TIMEOUT_SECONDS) * 1000)))
)

# Model selection
# - If GEMINI_MODEL is set to a concrete name, we try it first.
# - If GEMINI_MODEL is "auto" (default), we pick from preferred list.
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "auto").strip() or "auto"

# Common working examples in the official docs:
#   gemini-2.0-flash-001
#   gemini-2.5-flash
PREFERRED_MODELS: List[str] = [
    s.strip()
    for s in os.getenv(
        "GEMINI_MODEL_PREFERRED",
        "gemini-2.5-flash,gemini-2.0-flash-001,gemini-2.0-flash",
    ).split(",")
    if s.strip()
]

EXTRA_FALLBACKS: List[str] = [
    s.strip() for s in os.getenv("GEMINI_MODEL_FALLBACKS", "").split(",") if s.strip()
]


# -------------------------
# Result
# -------------------------
@dataclass
class LLMResult:
    status: str  # ok | timeout | error
    text: str
    ms: int
    attempts: int
    error: str = ""
    model: str = ""


# -------------------------
# Client & model cache
# -------------------------
_CLIENT = None
_MODEL_CACHE: Optional[Set[str]] = None
_MODEL_CACHE_AT = 0.0
_MODEL_CACHE_TTL_SECONDS = 10 * 60


def llm_enabled() -> bool:
    return bool(GEMINI_API_KEY) and genai is not None


def _normalize_model_name(name: str) -> str:
    n = (name or "").strip()
    if n.startswith("models/"):
        n = n[len("models/") :]
    return n


def get_gemini_client():
    global _CLIENT

    if _CLIENT is not None:
        return _CLIENT

    if not llm_enabled():
        raise RuntimeError("Gemini LLM is not enabled (missing GEMINI_API_KEY or google-genai)")

    if genai_types is not None:
        http_opts = genai_types.HttpOptions(api_version=GEMINI_API_VERSION, timeout=GEMINI_HTTP_TIMEOUT_MS)
        _CLIENT = genai.Client(api_key=GEMINI_API_KEY, http_options=http_opts)
    else:
        _CLIENT = genai.Client(api_key=GEMINI_API_KEY)

    return _CLIENT


def _refresh_model_cache(client) -> Set[str]:
    global _MODEL_CACHE, _MODEL_CACHE_AT

    now = time.time()
    if _MODEL_CACHE is not None and (now - _MODEL_CACHE_AT) < _MODEL_CACHE_TTL_SECONDS:
        return _MODEL_CACHE

    models: Set[str] = set()
    try:
        for m in client.models.list():
            name = getattr(m, "name", "") or ""
            if name:
                models.add(_normalize_model_name(name))
    except Exception:
        models = set()

    _MODEL_CACHE = models
    _MODEL_CACHE_AT = now
    return models


def _pick_model_candidates(client) -> List[str]:
    # explicit model
    if GEMINI_MODEL.lower() not in ("", "auto"):
        ordered = [GEMINI_MODEL] + [m for m in PREFERRED_MODELS if m != GEMINI_MODEL] + EXTRA_FALLBACKS
        seen = set()
        out: List[str] = []
        for m in ordered:
            m2 = _normalize_model_name(m)
            if not m2 or m2 in seen:
                continue
            seen.add(m2)
            out.append(m2)
        return out

    # auto mode
    available = _refresh_model_cache(client)

    if available:
        for m in PREFERRED_MODELS + EXTRA_FALLBACKS:
            m2 = _normalize_model_name(m)
            if m2 in available:
                ordered = [m2] + [x for x in (PREFERRED_MODELS + EXTRA_FALLBACKS) if _normalize_model_name(x) != m2]
                seen = set()
                out: List[str] = []
                for x in ordered:
                    x2 = _normalize_model_name(x)
                    if not x2 or x2 in seen:
                        continue
                    seen.add(x2)
                    out.append(x2)
                return out

    return [_normalize_model_name(x) for x in (PREFERRED_MODELS + EXTRA_FALLBACKS) if _normalize_model_name(x)]


def _is_model_not_found(err: Exception) -> bool:
    msg = str(err)
    return "404" in msg and "NOT_FOUND" in msg and ("models/" in msg or "model" in msg.lower())


def _is_quota_error(err: Exception) -> bool:
    msg = str(err).lower()
    return ("429" in msg or "resource_exhausted" in msg or "quota" in msg or "rate" in msg and "limit" in msg)


def _gemini_generate_sync(client, *, model: str, prompt: str, timeout_s: float) -> str:
    kwargs = {
        "model": model,
        "contents": prompt,
    }

    if genai_types is not None:
        kwargs["config"] = genai_types.GenerateContentConfig(
            temperature=0.2,
            max_output_tokens=800,
        )

    # SDK supports per-request timeout (seconds). If not available, retry without it.
    try:
        resp = client.models.generate_content(**kwargs, timeout=timeout_s)
    except TypeError:
        resp = client.models.generate_content(**kwargs)

    return (getattr(resp, "text", "") or "").strip()


def _backoff_ms(attempt_idx: int) -> int:
    return int(min(LLM_BACKOFF_MAX_MS, LLM_BACKOFF_BASE_MS * (2 ** attempt_idx)))


def _strip_code_fences(s: str) -> str:
    t = (s or "").strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else ""
        t = t.rsplit("```", 1)[0]
    return t.strip()


def _clean_llm_output(s: str) -> str:
    return _strip_code_fences(s)


def _now_ms() -> int:
    return int(time.time() * 1000)


def _elapsed_ms(start_ms: int) -> int:
    return max(0, _now_ms() - start_ms)


def _remaining_seconds(deadline: float) -> float:
    return max(0.0, deadline - time.time())


def _deadline_or_default(deadline: Optional[float]) -> float:
    return time.time() + LLM_TIMEOUT_SECONDS if deadline is None else deadline


def _deadline_to_timeout(deadline: float) -> float:
    # Small buffer so we don't overshoot
    return max(0.05, min(LLM_TIMEOUT_SECONDS, _remaining_seconds(deadline) - 0.05))


async def call_gemini_with_budget(client, prompt: str, deadline: Optional[float] = None) -> LLMResult:
    """Call Gemini within a time budget.

    - Tries multiple model candidates when configured (helps when a model name is deprecated).
    - Uses SDK per-request timeout + asyncio.wait_for.
    """

    if not llm_enabled():
        return LLMResult(status="error", text="", ms=0, attempts=0, error="llm_disabled", model="")

    if client is None:
        client = get_gemini_client()

    candidates = _pick_model_candidates(client)

    if not candidates:
        return LLMResult(status="error", text="", ms=0, attempts=0, error="no_model_candidates", model="")

    attempts_allowed = max(1, min(LLM_MAX_ATTEMPTS, len(candidates)))
    dl = _deadline_or_default(deadline)
    start_ms = _now_ms()

    last_err = ""

    for attempt in range(attempts_allowed):
        model = candidates[attempt]
        remaining = _deadline_to_timeout(dl)

        if remaining <= 0.1:
            return LLMResult(
                status="timeout",
                text="",
                ms=_elapsed_ms(start_ms),
                attempts=attempt,
                error=f"timeout: timeout within remaining={_remaining_seconds(dl):.2f}s",
                model=model,
            )

        try:
            text = await asyncio.wait_for(
                asyncio.to_thread(_gemini_generate_sync, client, model=model, prompt=prompt, timeout_s=remaining),
                timeout=remaining,
            )
            text = _clean_llm_output(text)
            if not text:
                last_err = "error: empty_response"
                continue

            return LLMResult(status="ok", text=text, ms=_elapsed_ms(start_ms), attempts=attempt + 1, model=model)

        except asyncio.TimeoutError:
            last_err = f"timeout: timeout within remaining={_remaining_seconds(dl):.2f}s"
            await asyncio.sleep(_backoff_ms(attempt) / 1000.0)
            continue
        except Exception as e:
            # model not found -> try next candidate without backoff
            if _is_model_not_found(e):
                last_err = f"error: {str(e)}"
                continue

            if _is_quota_error(e):
                last_err = f"quota: {str(e)}"
                await asyncio.sleep(_backoff_ms(attempt) / 1000.0)
                # Keep trying (maybe with the same model)
                continue

            last_err = f"error: {str(e)}"
            await asyncio.sleep(_backoff_ms(attempt) / 1000.0)
            continue

    return LLMResult(
        status="quota" if (last_err.startswith('quota:')) else ("timeout" if last_err.startswith('timeout:') else "error"),
        text="",
        ms=_elapsed_ms(start_ms),
        attempts=attempts_allowed,
        error=last_err or "error",
        model=candidates[min(attempts_allowed - 1, len(candidates) - 1)],
    )
