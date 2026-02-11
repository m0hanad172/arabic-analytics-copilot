import json
import urllib.request
import os

BASE = os.getenv("API_BASE", "http://127.0.0.1:8000/api")


def post(path: str, payload: dict):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        BASE + path,
        data=data,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8", errors="ignore"))

def main():
    q = {"question": "قارن صافي المبيعات والخصومات حسب المدينة والربع واعرض أعلى 5"}

    for path in [
        "/ask?use_llm=0&use_cache=0",
        "/ask?use_llm=1&use_cache=0",
        "/ask?use_llm=1&use_cache=1",
    ]:
        res = post(path, q)
        meta = res.get("meta", {})
        plan = res.get("plan", {})
        print("\n===", path, "===")
        print("llm_enabled:", meta.get("llm_enabled"))
        print("used_llm   :", meta.get("used_llm"))
        print("used_cache :", meta.get("used_cache"))
        print("plan.notes :", plan.get("notes"))
        print("duration_ms:", meta.get("duration_ms"))

if __name__ == "__main__":
    main()
