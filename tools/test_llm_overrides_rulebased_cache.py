import json
import time
import urllib.request

BASE = "http://127.0.0.1:8000"


def post(path: str, q: str) -> dict:
    url = f"{BASE}{path}"
    data = json.dumps({"question": q}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def main() -> None:
    token = time.strftime("%Y%m%d_%H%M%S")
    q = f"قارن صافي المبيعات والخصومات حسب المدينة والربع واعرض أعلى 5 (test:{token})"

    # 1) create rule_based plan AND cache it
    r1 = post("/ask?use_llm=0&use_cache=1", q)
    m1 = r1.get("meta", {})
    p1 = r1.get("plan", {})
    print("=== Step 1 (create cached rule_based) ===")
    print("used_llm   :", m1.get("used_llm"))
    print("used_cache :", m1.get("used_cache"))
    print("plan.notes :", p1.get("notes"))

    # 2) same question, but request LLM with cache enabled
    r2 = post("/ask?use_llm=1&use_cache=1", q)
    m2 = r2.get("meta", {})
    p2 = r2.get("plan", {})
    print("\n=== Step 2 (request LLM, cache enabled) ===")
    print("used_llm   :", m2.get("used_llm"))
    print("used_cache :", m2.get("used_cache"))
    print("plan.notes :", p2.get("notes"))

    # PASS condition: LLM was used OR plan is not rule_based anymore
    passed = (m2.get("used_llm") is True) and (p2.get("notes") != "rule_based")

    print("\n=== RESULT ===")
    print("PASS" if passed else "FAIL")
    if not passed:
        print("Expected: used_llm=True AND plan.notes != 'rule_based'")


if __name__ == "__main__":
    main()
