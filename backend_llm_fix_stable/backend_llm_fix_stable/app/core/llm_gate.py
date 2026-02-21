import os
from typing import Tuple

def llm_gate() -> Tuple[bool, str]:
    """
    Returns (enabled, reason).
    Use this to decide whether to call Gemini or fallback to rule-based.
    """
    enabled = os.getenv("LLM_ENABLED", "").strip().lower() in {"1","true","yes","on"}
    if not enabled:
        return False, "LLM_ENABLED is false/missing"

    key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not key:
        return False, "Missing GEMINI_API_KEY/GOOGLE_API_KEY"

    model = os.getenv("GEMINI_MODEL")
    if not model:
        return False, "Missing GEMINI_MODEL (will default if you want)"

    return True, "OK"
