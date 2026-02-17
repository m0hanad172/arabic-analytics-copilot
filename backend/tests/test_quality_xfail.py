import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from backend.app.main import app

client = TestClient(app)
CASES_PATH = Path(__file__).parent / "quality_cases.jsonl"

def _norm(s: str) -> str:
    return " ".join((s or "").lower().split())

def _extract_sql(resp_json: dict) -> str:
    return (
        (resp_json.get("result") or {}).get("sql")
        or resp_json.get("sql")
        or resp_json.get("generated_sql")
        or resp_json.get("debug_sql")
        or ""
    )

def _post_ask(question: str):
    # keep it simple; your API accepts {"question": "..."}
    r = client.post("/api/ask", params={"use_llm":"0","use_cache":"0","explain":"0"}, json={"question": question})
    if r.status_code == 404:
        r = client.post("/ask", params={"use_llm":"0","use_cache":"0","explain":"0"}, json={"question": question})
    return r

def _load_cases():
    cases = []
    for line in CASES_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        cases.append(json.loads(line))
    return cases

def test_quality_expected_failures():
    cases = _load_cases()
    assert cases, "quality_cases.jsonl is empty"

    for c in cases:
        r = _post_ask(c["question"])
        assert r.status_code == 200, f"{c['id']}: status={r.status_code}, body={r.text}"

        sql = _norm(_extract_sql(r.json()))
        expected = [t.lower() for t in (c.get("expect_sql") or [])]
        reason = c.get("xfail_reason")

        try:
            for tok in expected:
                assert tok in sql, f"{c['id']}: missing token {tok} in sql={sql}"
        except AssertionError:
            # expected to fail for now
            if reason:
                pytest.xfail(reason)
            raise

        # If it unexpectedly passes, fail loud (so you know it’s time to remove xfail)
        if reason:
            pytest.fail(f"{c['id']}: XPASS (remove xfail_reason) — now passing")
