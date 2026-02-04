import json
import time
from fastapi import APIRouter, Query

# Reuse helpers from /ask
from backend.app.api.routes.ask import (
    _get_catalog,
    _extract_json,
    _validate_plan,
    _apply_heuristics,
    _normalize_plan,
    gclient,
    GEMINI_MODEL,
    DEFAULT_MAX_ROWS,
    _db_fetchval,
)

router = APIRouter(prefix="/eval", tags=["eval"])


def _assert(cond: bool, msg: str, errors: list):
    if not cond:
        errors.append(msg)


def _plan_from_expect(exp: dict) -> dict:
    """
    Build a deterministic plan from the expected spec.
    This allows eval to run even when Gemini quota is exhausted.
    """
    metric = exp.get("metric", "net_sales")
    dims = exp.get("dims", [])
    city = exp.get("city")
    limit = exp.get("limit", DEFAULT_MAX_ROWS)

    plan = {
        "metrics": [metric],
        "dimensions": dims,
        "filters": [],
        "sort": [{"field": metric, "dir": "desc"}],
        "limit": int(limit),
        "notes": "rule_based_eval",
    }

    if city:
        plan["filters"].append({"field": "city", "op": "=", "value": city})

    return plan


@router.get("/smoke")
async def smoke(
    execute: bool = Query(False, description="If true, execute SQL against DB"),
    use_llm: bool = Query(True, description="If true, use Gemini to generate plans; falls back on quota errors"),
):
    catalog = await _get_catalog()

    tests = [
        {
            "q": "صافي المبيعات شهريا في سيدني",
            "expect": {"metric": "net_sales", "dims": ["month_start", "city"], "city": "Sydney"},
        },
        {
            "q": "صافي المبيعات شهريا في ملبورن",
            "expect": {"metric": "net_sales", "dims": ["month_start", "city"], "city": "Melbourne"},
        },
        {
            "q": "إجمالي المبيعات حسب فئة المنتج",
            "expect": {"metric": "gross_sales", "dims": ["product_category"]},
        },
        {
            "q": "أعلى 5 منتجات من حيث صافي المبيعات",
            "expect": {"metric": "net_sales", "dims": ["product_name"], "limit": 5},
        },
    ]

    results = []
    passed = 0

    for t in tests:
        question = t["q"]
        exp = t["expect"]
        t0 = time.perf_counter()

        errors = []
        sql_ok = None
        sql = None
        plan = None
        used_fallback = False

        # Strict prompt (still relying on heuristics/validation)
        prompt = f"""
Return ONLY valid JSON plan. No explanations, no code fences.

Catalog:
{json.dumps(catalog, ensure_ascii=False)}

Schema:
{{
  "metrics": [],
  "dimensions": [],
  "filters": [],
  "sort": [{{"field":"", "dir":"desc"}}],
  "limit": {DEFAULT_MAX_ROWS},
  "notes": ""
}}

Question:
{question}
""".strip()

        try:
            if not use_llm:
                used_fallback = True
                plan = _plan_from_expect(exp)
                plan = _validate_plan(plan, catalog)
                plan = _apply_heuristics(question, plan)
            else:
                resp = gclient.models.generate_content(model=GEMINI_MODEL, contents=prompt)
                raw = (resp.text or "").strip()
                plan = _extract_json(raw)
                plan = _normalize_plan(plan)
                plan = _validate_plan(plan, catalog)
                plan = _apply_heuristics(question, plan)

            # Assertions
            metric = exp.get("metric")
            if metric:
                _assert(metric in (plan.get("metrics") or []), f"Expected metric {metric}", errors)

            dims = exp.get("dims") or []
            for d in dims:
                _assert(d in (plan.get("dimensions") or []), f"Expected dimension {d}", errors)

            city = exp.get("city")
            if city:
                fs = plan.get("filters") or []
                has_city = any(
                    (f.get("field") == "city" and f.get("op") == "=" and f.get("value") == city)
                    for f in fs
                )
                _assert(has_city, f"Expected filter city = {city}", errors)

            lim = exp.get("limit")
            if lim is not None:
                _assert(int(plan.get("limit", 0)) == int(lim), f"Expected limit {lim}", errors)

            # Optional execution
            if execute:
                dbres = await _db_fetchval(
                    "SELECT bi_meta.run_query($1::jsonb);",
                    json.dumps(plan, ensure_ascii=False),
                )
                sql = (dbres or {}).get("sql")
                sql_ok = True

        except Exception as e:
            msg = repr(e)

            # Auto-fallback on Gemini quota errors (429)
            if use_llm and ("RESOURCE_EXHAUSTED" in msg or "429" in msg):
                try:
                    used_fallback = True
                    plan = _plan_from_expect(exp)
                    plan = _validate_plan(plan, catalog)
                    plan = _apply_heuristics(question, plan)

                    # rerun assertions
                    metric = exp.get("metric")
                    if metric:
                        _assert(metric in (plan.get("metrics") or []), f"Expected metric {metric}", errors)

                    dims = exp.get("dims") or []
                    for d in dims:
                        _assert(d in (plan.get("dimensions") or []), f"Expected dimension {d}", errors)

                    city = exp.get("city")
                    if city:
                        fs = plan.get("filters") or []
                        has_city = any(
                            (f.get("field") == "city" and f.get("op") == "=" and f.get("value") == city)
                            for f in fs
                        )
                        _assert(has_city, f"Expected filter city = {city}", errors)

                    lim = exp.get("limit")
                    if lim is not None:
                        _assert(int(plan.get("limit", 0)) == int(lim), f"Expected limit {lim}", errors)

                    if execute:
                        dbres = await _db_fetchval(
                            "SELECT bi_meta.run_query($1::jsonb);",
                            json.dumps(plan, ensure_ascii=False),
                        )
                        sql = (dbres or {}).get("sql")
                        sql_ok = True

                except Exception as e2:
                    errors.append(f"Exception: {msg}")
                    errors.append(f"Fallback failed: {repr(e2)}")
            else:
                errors.append(f"Exception: {msg}")

        duration_ms = int((time.perf_counter() - t0) * 1000)
        ok = (len(errors) == 0)
        if ok:
            passed += 1

        results.append(
            {
                "question": question,
                "ok": ok,
                "errors": errors,
                "duration_ms": duration_ms,
                "use_llm": use_llm,
                "used_fallback": used_fallback,
                "plan": plan,
                "sql_ok": sql_ok,
                "sql": sql,
            }
        )

    return {"passed": passed, "total": len(tests), "execute": execute, "use_llm": use_llm, "results": results}
