# Arabic Analytics Copilot (AAC)

Arabic Analytics Copilot is an Arabic **Natural Language → SQL** BI assistant.  
It converts Arabic questions into **safe SQL** (rule-based planning + optional Gemini LLM), runs them on PostgreSQL, and shows results in a modern dashboard (interactive table + filters + export + charts).

---

## What this project does
- Accepts an Arabic question (e.g., “اعرض عدد الطلبات حسب المدينة واعرض أعلى 5”)
- Generates a validated plan (dimensions/metrics/filters/sort/limit)
- Compiles the plan into guardrailed SQL
- Executes SQL on PostgreSQL
- Shows results in the UI (table + export + charts)
- Optionally uses Gemini LLM to improve planning when enabled

---

## Main Features
- Arabic question → SQL (rule-based planner + optional Gemini)
- SQL guardrails (single-statement safe SELECT patterns)
- Caching (faster repeated questions)
- UI:
  - Interactive results table (search / filters / column visibility / CSV export)
  - Visualization tab (charts)
- API health endpoint + Swagger docs

---

## Tech Stack
- Backend: FastAPI (Python)
- Frontend: React + TypeScript (Vite)
- Database: PostgreSQL (Docker)
- LLM (optional): Google Gemini

---

# Setup & Run (Step-by-step)

## 0) Prerequisites
- Git
- Node.js 18+
- Python 3.11+ recommended
- Docker Desktop (for PostgreSQL)

---

## 1) Clone the repository
```bash
git clone https://github.com/m0hanad172/arabic-analytics-copilot.git
cd arabic-analytics-copilot