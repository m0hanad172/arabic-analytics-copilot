# Arabic Analytics Copilot (AAC)

Arabic Analytics Copilot is an Arabic **Natural Language  SQL** BI assistant.
It converts Arabic questions into safe SQL (rule-based planning + optional Gemini LLM), runs it on PostgreSQL, and shows results in a modern dashboard (table + filters + export + charts).

## Features
- Arabic question  SQL (rule-based planner + optional Gemini)
- SQL guardrails (single-statement, safe SELECT patterns)
- Caching (faster repeated questions)
- UI:
  - Interactive table (search / filters / column visibility / CSV export)
  - Visualization tab (charts)
- API health endpoint + Swagger docs

## Tech Stack
- Backend: FastAPI (Python)
- Frontend: React + TypeScript (Vite)
- Database: PostgreSQL (Docker)
- LLM (optional): Google Gemini

---

# Quick Start

## Prerequisites
- Git
- Node.js 18+
- Python 3.11+ recommended
- Docker Desktop

## 1) Clone
git clone <REPO_URL>
cd arabic-analytics-copilot

## 2) Create env files
Create:
- backend/.env  (copy from backend/.env.example)
- frontend/.env (copy from frontend/.env.example)

Important: do NOT commit real secrets. Only commit the *.env.example files.

## 3) Start PostgreSQL (Docker)
From repo root:
docker compose up -d db

Check:
docker ps
docker exec -it aac-pg pg_isready -U aac -d aac

## 4) Database requirement
AAC expects:
- schema: bi
- schema: bi_meta
- view/table: bi.vw_fact_sales_line_clean

See db/README.md for details.

## 5) Run Backend
cd backend
python -m venv .venv
# Windows: .\.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

Backend URLs:
- Health: http://localhost:8000/api/health
- Docs:   http://localhost:8000/docs
- Ask:    POST http://localhost:8000/api/ask

## 6) Run Frontend
cd frontend
npm install
npm run dev

Frontend:
- http://localhost:5173

---

# Verify It Works (Smoke Test)

## Option A: Manual
- Open http://localhost:8000/docs
- Call POST /api/ask with a sample Arabic question

## Option B: PowerShell scripts (recommended)
If you have scripts/doctor.ps1 and scripts/smoke.ps1:
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\doctor.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\smoke.ps1

---

# LLM Notes (Gemini)
- Set GEMINI_API_KEY in backend/.env to enable Gemini.
- If the key is blocked (e.g., reported as leaked), generate a new key and update backend/.env.
- On LLM errors, the system falls back to rule-based planning automatically.

---

# License
Add your license here (MIT / Apache-2.0 / etc.)
