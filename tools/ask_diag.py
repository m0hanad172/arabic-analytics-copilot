import json
import time
import urllib.request
import os

BASE = os.getenv("API_BASE", "http://127.0.0.1:8000/api")

Q = "قارن صافي المبيعات والخصومات حسب المدينة والربع واعرض أعلى 5"

def post(path: str, timeout=20):
    url = BASE + path
    data = json.dumps({"question": Q}).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json; charset=utf-8"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode("utf-8", errors="ignore")
            dt = round((time.time() - t0) * 1000)
            print(f"[OK] {path} in {dt} ms")
            print(body[:800])
    except Exception as e:
        dt = round((time.time() - t0) * 1000)
        print(f"[FAIL] {path} after {dt} ms -> {e}")

if __name__ == "__main__":
    # isolate which step hangs
    post("/ask?use_llm=0&use_cache=0", timeout=20)  # rule-based only
    post("/ask?use_llm=1&use_cache=0", timeout=30)  # llm path
