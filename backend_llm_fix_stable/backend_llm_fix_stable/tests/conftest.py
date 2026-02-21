# backend/tests/conftest.py
import os
from pathlib import Path

def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k and v and k not in os.environ:
            os.environ[k] = v

def pytest_configure():
    # If DATABASE_URL already set, do nothing
    if os.environ.get("DATABASE_URL"):
        return

    # Try common env locations (backend/.env then project root/.env)
    here = Path(__file__).resolve()
    backend_dir = here.parents[1]          # .../backend
    root_dir = here.parents[2]             # .../ (project root)

    candidates = [
        backend_dir / ".env",
        backend_dir / ".env.local",
        root_dir / ".env",
        root_dir / ".env.local",
    ]

    for p in candidates:
        _load_env_file(p)
        if os.environ.get("DATABASE_URL"):
            return

    # Safe fallback (matches your current config style)
    os.environ["DATABASE_URL"] = "postgresql+asyncpg://copilot_ro:123@127.0.0.1:5432/arabic_analytics"
