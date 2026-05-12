"""Helper that generates 005_seed_bi_meta.sql from the PG export.

Reads ``docs/.bi_meta_export.json`` (a read-only audit dump produced
during Phase C3) and emits T-SQL ``MERGE`` upserts for
bi_meta.metrics, bi_meta.dimensions, and bi_meta.synonyms. The
PostgreSQL ``sql_expression`` strings are translated into T-SQL
equivalents.

This script is *only* a build helper for the seed file; it is not
executed at runtime. Run manually to regenerate the seed:

    python -m backend.db.sqlserver._gen_seed > backend/db/sqlserver/005_seed_bi_meta.sql
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EXPORT = ROOT / "docs" / ".bi_meta_export.json"


# ---- translators ----------------------------------------------------------
_PG_NUMERIC_CAST = re.compile(r"::numeric\b", flags=re.IGNORECASE)
_PG_BIGINT_CAST = re.compile(r"::bigint\b", flags=re.IGNORECASE)
_PG_INT_CAST = re.compile(r"::int(?:eger)?\b", flags=re.IGNORECASE)
_PG_DATE_CAST = re.compile(r"::date\b", flags=re.IGNORECASE)
_COUNT_STAR = re.compile(r"\bCOUNT\s*\(\s*\*\s*\)\s*(?:::bigint)?", flags=re.IGNORECASE)


def _strip_casts(expr: str) -> str:
    e = _PG_NUMERIC_CAST.sub("", expr)
    e = _PG_BIGINT_CAST.sub("", e)
    e = _PG_INT_CAST.sub("", e)
    e = _PG_DATE_CAST.sub("", e)
    return e


def translate_metric_expr(expr: str, agg: str) -> str:
    """Translate a PG metric sql_expression to T-SQL."""
    e = expr.strip()
    if _COUNT_STAR.fullmatch(e) or (agg or "").lower() == "count":
        return "COUNT_BIG(*)"
    e = _strip_casts(e).strip()
    # Wrap INT columns in CAST so AVG/SUM return a decimal, mirroring PG.
    INT_COLS = {"f.ship_delay_days", "f.order_quantity"}
    for col in INT_COLS:
        # e.g. SUM(f.order_quantity) or AVG(f.ship_delay_days)
        e = re.sub(
            rf"({col.replace('.', '[.]')})(?=\s*\))",
            f"CAST({col} AS DECIMAL(38, 6))",
            e,
        )
    return e


def translate_dimension_expr(expr: str, key: str) -> str:
    """Translate a PG dimension sql_expression to T-SQL."""
    e = expr.strip()
    if key == "order_year":
        return "DATEPART(year, f.order_date_d)"
    if key == "order_quarter":
        return "DATEPART(quarter, f.order_date_d)"
    if key == "order_month":
        return "DATEPART(month, f.order_date_d)"
    if key == "month_start":
        return "DATEFROMPARTS(YEAR(f.order_date_d), MONTH(f.order_date_d), 1)"
    # Fall back: just strip casts.
    return _strip_casts(e).strip()


def q(s: str | None) -> str:
    if s is None:
        return "NULL"
    return "N'" + str(s).replace("'", "''") + "'"


def b(v) -> str:
    return "1" if bool(v) else "0"


# ---- emit -----------------------------------------------------------------
def main() -> None:
    data = json.loads(EXPORT.read_text(encoding="utf-8"))

    print("/*")
    print(" * 005_seed_bi_meta.sql  (Phase C3)")
    print(" *")
    print(" * Seeds bi_meta.metrics, bi_meta.dimensions, and bi_meta.synonyms")
    print(" * with the same rows the PostgreSQL catalog uses today, translated")
    print(" * to T-SQL expressions. Idempotent (MERGE).")
    print(" *")
    print(" * Generated from docs/.bi_meta_export.json by")
    print(" * backend/db/sqlserver/_gen_seed.py. Regenerate after editing the")
    print(" * PG catalog if needed.")
    print(" */")
    print("USE ArabicAnalytics;")
    print("GO")
    print()

    # ---- metrics ----
    print("-- ---------------------------------------------------------------------------")
    print("-- bi_meta.metrics")
    print("-- ---------------------------------------------------------------------------")
    print("MERGE bi_meta.metrics AS tgt")
    print("USING (VALUES")
    rows = []
    for m in sorted(data["metrics"], key=lambda r: r["metric_key"]):
        tsql = translate_metric_expr(m["sql_expression"], m["agg"])
        rows.append(
            "    ("
            + ", ".join([
                q(m["metric_key"]),
                q(m["display_name_ar"]),
                q(m["display_name_en"]),
                q(m["agg"]),
                q(tsql),
                q(m["data_type"]),
                q(m.get("format_hint")),
            ])
            + ")"
        )
    print(",\n".join(rows))
    print(") AS src(metric_key, display_name_ar, display_name_en, agg, sql_expression, data_type, format_hint)")
    print("ON tgt.metric_key = src.metric_key")
    print("WHEN MATCHED THEN UPDATE SET")
    print("    display_name_ar = src.display_name_ar,")
    print("    display_name_en = src.display_name_en,")
    print("    agg             = src.agg,")
    print("    sql_expression  = src.sql_expression,")
    print("    data_type       = src.data_type,")
    print("    format_hint     = src.format_hint")
    print("WHEN NOT MATCHED THEN INSERT")
    print("    (metric_key, display_name_ar, display_name_en, agg, sql_expression, data_type, format_hint)")
    print("    VALUES (src.metric_key, src.display_name_ar, src.display_name_en, src.agg, src.sql_expression, src.data_type, src.format_hint);")
    print("GO")
    print()

    # ---- dimensions ----
    print("-- ---------------------------------------------------------------------------")
    print("-- bi_meta.dimensions")
    print("-- ---------------------------------------------------------------------------")
    print("MERGE bi_meta.dimensions AS tgt")
    print("USING (VALUES")
    rows = []
    for d in sorted(data["dimensions"], key=lambda r: r["dim_key"]):
        tsql = translate_dimension_expr(d["sql_expression"], d["dim_key"])
        rows.append(
            "    ("
            + ", ".join([
                q(d["dim_key"]),
                q(d["display_name_ar"]),
                q(d["display_name_en"]),
                q(tsql),
                q(d["data_type"]),
                b(d["allowed_grouping"]),
            ])
            + ")"
        )
    print(",\n".join(rows))
    print(") AS src(dim_key, display_name_ar, display_name_en, sql_expression, data_type, allowed_grouping)")
    print("ON tgt.dim_key = src.dim_key")
    print("WHEN MATCHED THEN UPDATE SET")
    print("    display_name_ar  = src.display_name_ar,")
    print("    display_name_en  = src.display_name_en,")
    print("    sql_expression   = src.sql_expression,")
    print("    data_type        = src.data_type,")
    print("    allowed_grouping = src.allowed_grouping")
    print("WHEN NOT MATCHED THEN INSERT")
    print("    (dim_key, display_name_ar, display_name_en, sql_expression, data_type, allowed_grouping)")
    print("    VALUES (src.dim_key, src.display_name_ar, src.display_name_en, src.sql_expression, src.data_type, src.allowed_grouping);")
    print("GO")
    print()

    # ---- synonyms ----
    print("-- ---------------------------------------------------------------------------")
    print("-- bi_meta.synonyms")
    print("-- ---------------------------------------------------------------------------")
    print("MERGE bi_meta.synonyms AS tgt")
    print("USING (VALUES")
    rows = []
    for s in sorted(data["synonyms"], key=lambda r: (r["term"], r["maps_to_type"], r["maps_to_key"])):
        rows.append(
            "    ("
            + ", ".join([
                q(s["term"]),
                q(s["maps_to_type"]),
                q(s["maps_to_key"]),
            ])
            + ")"
        )
    print(",\n".join(rows))
    print(") AS src(term, maps_to_type, maps_to_key)")
    print("ON tgt.term = src.term")
    print("WHEN MATCHED THEN UPDATE SET")
    print("    maps_to_type = src.maps_to_type,")
    print("    maps_to_key  = src.maps_to_key")
    print("WHEN NOT MATCHED THEN INSERT")
    print("    (term, maps_to_type, maps_to_key)")
    print("    VALUES (src.term, src.maps_to_type, src.maps_to_key);")
    print("GO")


if __name__ == "__main__":
    main()
