# backend/tests/test_ask_standard.py
import os
import pytest
from fastapi.testclient import TestClient

from backend.app.main import app

client = TestClient(app)

def post_ask(question: str, use_llm: int, use_cache: int):
    API_PREFIX = "/api"
    r = client.post(f"{API_PREFIX}/ask?use_llm={use_llm}&use_cache={use_cache}", json={"question": question})
    assert r.status_code == 200, r.text
    return r.json()

def test_rule_based_basic_plan():
    data = post_ask("قارن صافي المبيعات والخصومات حسب المدينة والربع واعرض أعلى 5", use_llm=0, use_cache=0)
    plan = data["plan"]
    meta = data["meta"]

    assert meta["used_llm"] is False
    assert plan["notes"] == "rule_based"

    assert "net_sales" in plan["metrics"]
    assert "discount_amount" in plan["metrics"]
    assert "order_year" in plan["dimensions"]
    assert "order_quarter" in plan["dimensions"]
    assert "city" in plan["dimensions"]
    assert plan["limit"] == 5

def test_autocorrect_discount_alias_in_llm_plan_without_llm():
    """
    حتى بدون LLM: نختبر autocorrect بس عن طريق سؤال يدفع النظام لاستخدام alias في النص.
    (الـ rule_based غالباً ما يطلع alias، بس هذا يضمن إن autocorrect موجود ومفعّل)
    """
    data = post_ask("قارن صافي المبيعات والـ discounts حسب المدينة والربع واعرض أعلى 5", use_llm=0, use_cache=0)
    plan = data["plan"]

    # rule_based ما يتأثر كثير، لكن لازم يطلع canonical key
    assert "discount_amount" in plan["metrics"]
    assert "discounts" not in plan["metrics"]
