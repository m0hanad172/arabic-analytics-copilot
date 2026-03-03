# Arabic Analytics Copilot (AAC) 

Arabic Analytics Copilot is an Arabic **Natural Language → SQL** BI assistant.  
It converts Arabic questions into a validated analytics **plan**, compiles it into **guardrailed SQL**, executes on Postgres, and returns results to a modern React dashboard.

---

## Table of Contents
1. Architecture Overview (Mental Model)
2. Repo Layout (What matters)
3. Database Model (bi / bi_meta)
4. Roles & Permissions (copilot_ro vs copilot_loader)
5. Running the Project (DB + Backend + Frontend)
6. Restoring DB from Dump (safe path)
7. Rebuilding DB from CSV (Phase4 bootstrap path)
8. API Endpoints
9. Ask Pipeline Internals (runner → plan → SQL → guardrails → execute → cache)
10. Cache & Logs Internals (plan_cache / query_log)
11. Arabic Encoding Notes (PowerShell gotchas)
12. Testing & Diagnostics
13. Common Failure Modes (and fixes)

---

# 1) Architecture Overview (Mental Model)

**Frontend (React/Vite)**
- Sends `question` to backend `/api/ask`
- Displays table + filters + export + charts
- Has client-side utilities (CSV export, time utils, etc.)

**Backend (FastAPI)**
- Receives request → builds plan → compiles SQL → guardrails → executes → returns rows + meta
- Optionally uses Gemini LLM for planning (when enabled)
- Exposes API docs at `/docs`

**Database (Postgres)**
- `bi` schema: fact table + safe views used at runtime
- `bi_meta` schema: semantic layer (metrics/dimensions/synonyms) + SQL compiler + cache tables

---

# 2) Repo Layout (What matters)

Top-level “important” items:
- `compose.db.yml` : DB-only compose
- `db/` : contains `db_dump.sql` (full dump used for restore)
- `scripts/restore_db.ps1` : restore script
- `request_test.py` : Arabic-safe API test (recommended)
- `backend/.env.example` and `frontend/.env.example` : environment templates
- Backend core files:
  - `backend/app/main.py` (app entry)
  - `backend/app/core/config.py` (settings)
  - `backend/app/core/sql_guardrails.py` (SQL safety)
  - `backend/app/services/ask/runner.py` (main ask pipeline)
- Frontend core files:
  - `frontend/src/services/askApi.ts` (API client)
  - `frontend/src/store/useAskStore.ts` (state)
  - `frontend/src/app/layout/App.tsx` + `src/App.tsx` (UI entry)

⚠️ Do NOT commit:
- `frontend/node_modules/` (huge)
- `.venv/`
- `backend/.env` and `frontend/.env` (secrets / local values)
Keep only `*.env.example` tracked.

---

# 3) Database Model (bi / bi_meta)

## 3.1 bi schema (runtime data)
- Runtime queries should target safe view(s), mainly:
  - `bi.vw_fact_sales_line_clean`
- Fact table exists (demo dataset):
  - `bi.fact_sales_line`

## 3.2 bi_meta schema (semantic layer + runtime helpers)
Tables:
- `bi_meta.metrics`:
  - `metric_key`, `display_name_ar`, `display_name_en`, `agg`, `sql_expression`, `data_type`
- `bi_meta.dimensions`:
  - `dim_key`, `display_name_ar/en`, `sql_expression`, etc.
- `bi_meta.synonyms`:
  - Maps Arabic terms → canonical keys

Functions:
- `bi_meta.get_catalog()` and `bi_meta.get_catalog('bi')`:
  - Returns semantic catalog JSON consumed by backend
- `bi_meta.compile_query(plan jsonb)`:
  - Plan → SQL (SELECT-only)
- `bi_meta.run_query(plan jsonb)`:
  - Executes compiled SQL and returns rows JSON

---

# 4) Roles & Permissions (Security model)

We use two DB users (principle of least privilege):

- `copilot_loader` (Write / bootstrap user)
  - Used for initial load, schema build, seeding
  - Needs CREATE/INSERT permissions

- `copilot_ro` (Read-only runtime user)
  - Used by backend during normal operation
  - Should have SELECT on safe views + EXECUTE on catalog/compiler functions
  - Should NOT have DROP/UPDATE/DELETE privileges (reduces risk even if LLM goes wrong)

---

# 5) Running the Project (DB + Backend + Frontend)

## 5.1 Start Postgres (Docker)
```powershell
# Start DB in background
docker compose -f compose.db.yml -p aac up -d

# Check it is accepting connections
docker exec -it aac-pg pg_isready -U postgres -d arabic_analytics
````

### Container name conflict (only if DB already running)

If you see: `container name "/aac-pg" is already in use`

* That means Postgres is already running → you can skip “start DB”.
* Or restart it safely (no volume deletion):

```powershell
docker stop aac-pg
docker rm aac-pg
docker compose -f compose.db.yml -p aac up -d
```

⚠️ DO NOT use `down -v` and DO NOT prune volumes unless you want to delete the DB.

## 5.2 Backend (local dev)

```powershell
# Create venv (once)
python -m venv .venv

# Activate
.\.venv\Scripts\Activate.ps1

# Install deps
pip install -r backend\requirements.txt

# Create env file from template
Copy-Item backend\.env.example backend\.env
```

Edit `backend\.env`:

```env
DATABASE_URL=postgresql+asyncpg://copilot_ro:123@localhost:5432/arabic_analytics
ALLOWED_SCHEMA=bi
SQL_ALLOWED_SCHEMAS=bi
```

Run:

```powershell
uvicorn backend.app.main:app --reload --port 8000
```

API docs:

* [http://localhost:8000/docs](http://localhost:8000/docs)

## 5.3 Frontend (Vite)

```powershell
cd frontend
npm install
npm run dev
```

UI:

* [http://localhost:3000](http://localhost:3000)

---

# 6) Restoring DB from Dump (safe path for new machines)

This repo includes:

* `db/db_dump.sql` (full DB: schemas + functions + data)

Restore:

```powershell
docker exec -i aac-pg psql -U postgres -d arabic_analytics < db/db_dump.sql
```

Or use the script:

```powershell
.\scripts\restore_db.ps1
```

Verify:

```powershell
docker exec -it aac-pg psql -U postgres -d arabic_analytics -c "\dn"
docker exec -it aac-pg psql -U postgres -d arabic_analytics -c "select count(*) from bi.fact_sales_line;"
```

---

# 7) Rebuilding DB from CSV (Phase4 bootstrap path)

Alternative to dump restore (useful for dev/experiments):

* Copy CSV into container (path expected by bootstrap)
* Run:

  * `backend/app/db/db_bootstrap.sql`
  * `backend/app/db/phase4_db_bootstrap.sql`
* There is also a helper script under `tools/restore_phase4.ps1` (advanced).

(If you don’t need rebuild, prefer dump restore — faster and consistent.)

---

# 8) API Endpoints (Backend routes)

Main API routes exist under `backend/app/api/routes/`:

* `ask` (core endpoint)
* `health`
* `schema`
* `query`
* `logs`
* `eval`
* `transcribe` (if enabled)

---

# 9) Ask Pipeline Internals (High-level)

When calling `/api/ask`:

1. Normalize question (Arabic-safe normalization)
2. Load catalog from `bi_meta.get_catalog()` (DB function)
3. Decide cache hit/miss for plan (plan_cache)
4. Build plan:

   * Rule-based planner (default)
   * Optional LLM planner (if enabled)
5. Compile plan → SQL (bi_meta.compile_query or internal compiler)
6. Guardrails validate SQL (single statement, SELECT-only rules)
7. Execute SQL
8. Return:

   * plan
   * SQL
   * rows
   * meta: timings, cache info, catalog hash/source

---

# 10) Cache & Logs Internals

* `bi_meta.plan_cache`:

  * Unique key typically based on normalized question + catalog_hash
  * Allows repeated questions to be fast
* `bi_meta.query_log`:

  * Stores question + plan + SQL + row_count + timings
  * Useful for debugging and evaluation

---

# 11) Arabic Encoding Notes (PowerShell gotchas)

PowerShell sometimes corrupts Arabic JSON requests and shows `????`.

Recommended: use the included Python test:

```powershell
python request_test.py
```

Alternative: PowerShell UTF-8 bytes request:

```powershell
$api = "http://localhost:8000/api"
$payload = @{ question="اعرض صافي المبيعات حسب المدينة واعرض أعلى 5"; use_cache=1; use_llm=0 }
$json  = $payload | ConvertTo-Json -Depth 6
$bytes = [System.Text.Encoding]::UTF8.GetBytes($json)
Invoke-RestMethod "$api/ask" -Method Post -ContentType "application/json; charset=utf-8" -Body $bytes
```

---

# 12) Testing & Diagnostics

* Run tests (backend):

```powershell
pytest -q
```

* Quick DB check:

```powershell
docker exec -it aac-pg psql -U postgres -d arabic_analytics -c "select count(*) from bi.fact_sales_line;"
docker exec -it aac-pg psql -U postgres -d arabic_analytics -c "select bi_meta.get_catalog('bi');"
```

* API sanity test:

```powershell
python request_test.py
```

---

# 13) Common Failure Modes (and fixes)

## A) DB deleted / missing data

Cause: running `docker compose down -v` or prune volumes.
Fix: start DB and restore from `db/db_dump.sql`.

## B) `ModuleNotFoundError: psycopg2`

Cause: DATABASE_URL not using asyncpg.
Fix: set:
`postgresql+asyncpg://...`

## C) Container name conflict

Cause: `aac-pg` already running.
Fix: skip starting DB OR stop/remove container (without volume deletion).

## D) Arabic appears as `????`

Cause: request encoding in PowerShell.
Fix: `request_test.py` or UTF-8 bytes request.

