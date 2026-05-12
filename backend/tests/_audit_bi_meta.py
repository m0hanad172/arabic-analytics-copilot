"""Read-only introspection helper for Phase C1 bi_meta audit.

Run via: python -m backend.tests._audit_bi_meta

Prints catalog of every object in schema bi_meta. Touches only
information_schema and pg_catalog (read-only). Does NOT modify data.
"""
from __future__ import annotations

import asyncio
import os
import sys

import asyncpg  # type: ignore


async def main() -> None:
    url = os.getenv("DATABASE_URL", "")
    if url.startswith("postgresql+asyncpg://"):
        url = "postgresql://" + url[len("postgresql+asyncpg://"):]
    if not url:
        print("DATABASE_URL is not set", file=sys.stderr)
        sys.exit(1)

    conn = await asyncpg.connect(url)
    try:
        print("=== TABLES & VIEWS in bi_meta ===")
        rows = await conn.fetch(
            """
            SELECT table_name, table_type
            FROM information_schema.tables
            WHERE table_schema = 'bi_meta'
            ORDER BY table_type, table_name;
            """
        )
        for r in rows:
            print(f"  [{r['table_type']}] {r['table_name']}")

        print("\n=== COLUMNS for each bi_meta table/view ===")
        cols = await conn.fetch(
            """
            SELECT table_name, column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_schema = 'bi_meta'
            ORDER BY table_name, ordinal_position;
            """
        )
        cur = None
        for c in cols:
            if c["table_name"] != cur:
                cur = c["table_name"]
                print(f"\n  -- {cur} --")
            print(f"    {c['column_name']:<30} {c['data_type']:<24} null={c['is_nullable']}")

        print("\n=== FUNCTIONS in bi_meta ===")
        funcs = await conn.fetch(
            """
            SELECT
              p.proname AS name,
              pg_catalog.pg_get_function_identity_arguments(p.oid) AS args,
              pg_catalog.pg_get_function_result(p.oid) AS returns,
              CASE p.prokind
                WHEN 'f' THEN 'function'
                WHEN 'p' THEN 'procedure'
                WHEN 'a' THEN 'aggregate'
                WHEN 'w' THEN 'window'
              END AS kind,
              l.lanname AS language
            FROM pg_catalog.pg_proc p
            JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace
            JOIN pg_catalog.pg_language l ON l.oid = p.prolang
            WHERE n.nspname = 'bi_meta'
            ORDER BY p.proname, args;
            """
        )
        for f in funcs:
            print(f"\n  {f['kind']} bi_meta.{f['name']}({f['args']}) returns {f['returns']} [{f['language']}]")

        print("\n=== FULL FUNCTION SOURCES ===")
        for fname in ("get_catalog", "compile_query", "run_query", "log_query"):
            srcs = await conn.fetch(
                """
                SELECT p.proname,
                       pg_catalog.pg_get_function_identity_arguments(p.oid) AS args,
                       pg_catalog.pg_get_functiondef(p.oid) AS src
                FROM pg_catalog.pg_proc p
                JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace
                WHERE n.nspname = 'bi_meta' AND p.proname = $1
                ORDER BY p.proname, args;
                """,
                fname,
            )
            for s in srcs:
                print(f"\n----- bi_meta.{s['proname']}({s['args']}) -----")
                print(s["src"])

        print("\n=== ROW COUNTS for bi_meta tables (approx via reltuples) ===")
        rc = await conn.fetch(
            """
            SELECT c.relname AS name,
                   c.relkind,
                   c.reltuples::bigint AS approx_rows
            FROM pg_catalog.pg_class c
            JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'bi_meta' AND c.relkind IN ('r', 'v', 'm')
            ORDER BY c.relkind, c.relname;
            """
        )
        for r in rc:
            print(f"  {r['relkind']} {r['name']:<30} ~{r['approx_rows']} rows")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
