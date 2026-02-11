# backend/tests/test_ask_llm_optional.py
import os
import pytest
from fastapi.testclient import TestClient
from backend.app.main import app

client = TestClient(app)

def post_ask(question: str, use_llm: int, use_cache: int):
    r = client.post(f"/api/ask?use_llm={use_llm}&use_cache={use_cache}", json={"question": question})
    assert r.status_code == 200, r.text
    return r.json()

@pytest.mark.skipif(
    not (os.getenv("GEMINI_API_KEY") and os.getenv("RUN_LLM_TESTS") == "1"),
    reason="LLM tests disabled (set RUN_LLM_TESTS=1 and GEMINI_API_KEY)."
)
def test_llm_path_runs():
    data = post_ask("قارن صافي المبيعات والخصومات حسب المدينة والربع واعرض أعلى 5", use_llm=1, use_cache=0)
    assert data["meta"]["llm_attempted"] is True
    # ممكن يفشل بسبب quota، بس على الأقل نعرف انه حاول
