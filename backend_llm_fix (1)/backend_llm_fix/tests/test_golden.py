import json
from pathlib import Path
from fastapi.testclient import TestClient

from backend.app.main import app

client = TestClient(app)

GOLDEN_PATH = Path(__file__).parent / "golden_questions.jsonl"

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

def _extract_rows(resp_json: dict):
    return (
        (resp_json.get("result") or {}).get("rows")
        or resp_json.get("rows")
        or []
    )

def _post_ask(question: str, opts: dict):
    endpoints = ["/api/ask", "/ask"]
    params = {
        "use_llm": "1" if opts.get("use_llm") else "0",
        "use_cache": "1" if opts.get("use_cache") else "0",
        "explain": "1" if opts.get("explain") else "0",
    }
    payloads = [
        {"question": question},
        {"q": question},
        {"query": question},
        {"text": question},
        {"question": question, "limit": 200},
    ]

    last = None
    for ep in endpoints:
        for body in payloads:
            r = client.post(ep, params=params, json=body)
            last = r
            if r.status_code == 404:
                break
            if r.status_code == 422:
                continue
            return r
    return last

def _load_cases():
    cases = []
    for line in GOLDEN_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        cases.append(json.loads(line))
    return cases

def _assert_single_statement(sql_raw: str, case_id: str):
    s = (sql_raw or "").strip()
    if not s:
        return
    semi = s.count(";")
    # allow at most one semicolon
    assert semi <= 1, f"{case_id}: possible multi-statement (more than one ';')"
    # if present, it must be trailing only
    if semi == 1:
        assert s.endswith(";"), f"{case_id}: ';' must be only at the end"
        assert ";" not in s[:-1], f"{case_id}: ';' found in the middle (multi-statement risk)"

def test_golden_suite():
    cases = _load_cases()
    assert cases, "golden_questions.jsonl is empty"

    for c in cases:
        q = c["question"]
        opts = c.get("opts", {})
        r = _post_ask(q, opts)

        assert r is not None, f"{c['id']}: no response"
        assert r.status_code == 200, f"{c['id']}: status={r.status_code}, body={r.text}"

        j = r.json()
        sql_raw = _extract_sql(j)
        sql = _norm(sql_raw)
        rows = _extract_rows(j)

        assert isinstance(rows, list), f"{c['id']}: rows is not a list"
        min_rows = int(c.get("min_rows", 0))
        assert len(rows) >= min_rows, f"{c['id']}: rows={len(rows)} < {min_rows}"

        # ✅ semicolon is allowed only as a trailing terminator
        _assert_single_statement(sql_raw, c["id"])

        # SQL guardrails sanity (no destructive ops, etc.)
        for bad in c.get("forbid_sql", []):
            if bad.strip() == ";":
                continue  # allow trailing terminator
            assert bad.lower() not in sql, f"{c['id']}: forbidden token in sql -> {bad}"

        for tok in c.get("expect_sql", []):
            assert tok.lower() in sql, f"{c['id']}: expected token missing in sql -> {tok}"
