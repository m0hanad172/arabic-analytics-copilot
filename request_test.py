import requests, json

payload = {
  "question": "اعرض صافي المبيعات حسب المدينة واعرض أعلى 5",
  "use_cache": 0,
  "use_llm": 0
}

r = requests.post("http://localhost:8000/api/ask", json=payload, timeout=30)
print("status:", r.status_code)
print(json.dumps(r.json(), ensure_ascii=False, indent=2))
