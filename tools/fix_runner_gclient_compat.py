from __future__ import annotations

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


def replace_top_level_function(src: str, fn_name: str, new_block: str) -> str:
    lines = src.splitlines(True)
    start = None
    for i, line in enumerate(lines):
        if line.startswith(f"def {fn_name}("):
            start = i
            break
    if start is None:
        raise SystemExit(f"Could not find function: def {fn_name}(...")

    # find end: next top-level def/async def (indent 0), after start
    end = None
    for j in range(start + 1, len(lines)):
        if lines[j].startswith("def ") or lines[j].startswith("async def "):
            end = j
            break
    if end is None:
        end = len(lines)

    return "".join(lines[:start]) + new_block + "".join(lines[end:])


def main() -> None:
    if not RUNNER.exists():
        raise SystemExit(f"runner.py not found: {RUNNER}")

    src = RUNNER.read_text(encoding="utf-8")

    new_get_gclient = r'''
def _get_gclient():
    """
    Lazy-init Gemini client with compatibility:
      - New SDK: `from google import genai`  -> genai.Client(...)
      - Legacy SDK: `import google.generativeai as genai` -> genai.GenerativeModel(...)
    Returns a client that supports: gclient.models.generate_content(model=..., contents=...)
    """
    global gclient
    if gclient is not None:
        return gclient

    # Defensive checks (runner.py already has these globals عادة)
    api_key = globals().get("GEMINI_API_KEY") or ""
    if not api_key:
        gclient = None
        return None

    model_name = (
        globals().get("GEMINI_MODEL")
        or globals().get("MODEL_NAME")
        or "gemini-1.5-flash"
    )

    # --- Try NEW SDK (google-genai) ---
    try:
        from google import genai as genai_new  # type: ignore
        if hasattr(genai_new, "Client"):
            gclient = genai_new.Client(api_key=api_key)
            return gclient
    except Exception:
        pass

    # --- Try LEGACY SDK (google-generativeai) ---
    try:
        import google.generativeai as genai_legacy  # type: ignore

        # configure once
        try:
            genai_legacy.configure(api_key=api_key)
        except Exception:
            pass

        model = genai_legacy.GenerativeModel(model_name)

        class _CompatModels:
            def __init__(self, m):
                self._m = m

            def generate_content(self, *args, **kwargs):
                # new SDK uses: generate_content(model=..., contents=...)
                contents = kwargs.get("contents")
                if contents is None:
                    # fallback positional
                    if len(args) >= 2:
                        contents = args[1]
                    elif len(args) == 1:
                        contents = args[0]
                    else:
                        contents = ""

                return self._m.generate_content(contents)

        class _CompatClient:
            def __init__(self, m):
                self.models = _CompatModels(m)

        gclient = _CompatClient(model)
        return gclient
    except Exception:
        gclient = None
        return None


'''.lstrip("\n")

    b = backup(RUNNER)
    src2 = replace_top_level_function(src, "_get_gclient", new_get_gclient)
    RUNNER.write_text(src2, encoding="utf-8")

    print("✅ Patched runner.py: _get_gclient now supports NEW+LEGACY Gemini SDK (compat client)")
    print(f"- Backup: {b}")


if __name__ == "__main__":
    main()
