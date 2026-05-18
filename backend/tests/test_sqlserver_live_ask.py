from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.skipif(
    os.getenv("SQLSERVER_LIVE") != "1",
    reason="set SQLSERVER_LIVE=1 to run the live SQL Server /ask smoke",
)
def test_live_sqlserver_ask_smoke_script():
    root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")

    proc = subprocess.run(
        [sys.executable, str(root / "scripts" / "smoke_sqlserver_ask.py")],
        cwd=root,
        env=env,
        text=True,
        capture_output=True,
        timeout=120,
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "skipped_for_sqlserver: None" in proc.stdout
