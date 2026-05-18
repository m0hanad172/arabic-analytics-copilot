from __future__ import annotations

import json
from typing import Any, Callable, Optional

from sqlalchemy import text

from backend.app.db.adapter import (
    ensure_json_obj,
    is_postgres,
    is_sqlserver,
    pg_fetchrow,
    pg_fetchval,
)


PgFetchVal = Callable[..., Any]
PgFetchRow = Callable[..., Any]


async def get_cached_plan(
    question_norm: str,
    catalog_hash: str,
    *,
    pg_fetchrow_func: Optional[PgFetchRow] = None,
    ensure_json_func: Callable[[Any], Any] = ensure_json_obj,
) -> Optional[dict]:
    """Read a cached plan for the active backend.

    Cache persistence is best-effort in the historical /ask path, so this
    helper keeps that contract: any DB-side problem becomes a cache miss.
    """
    try:
        if is_postgres():
            fetchrow = pg_fetchrow_func or pg_fetchrow
            row = await fetchrow(
                """
                SELECT id, plan, model
                FROM bi_meta.plan_cache
                WHERE question_norm=$1 AND catalog_hash=$2
                ORDER BY updated_at DESC
                LIMIT 1;
                """,
                question_norm,
                catalog_hash,
            )
            if not row:
                return None
            row["plan"] = ensure_json_func(row.get("plan"))
            return row

        if is_sqlserver():
            from backend.app.db.session import SessionLocal

            async with SessionLocal() as session:
                result = await session.execute(
                    text(
                        """
                        SELECT TOP (1) id, [plan], model
                        FROM bi_meta.plan_cache
                        WHERE question_norm = :question_norm
                          AND catalog_hash = :catalog_hash
                        ORDER BY updated_at DESC;
                        """
                    ),
                    {
                        "question_norm": question_norm,
                        "catalog_hash": catalog_hash,
                    },
                )
                row = result.mappings().first()
            if not row:
                return None
            out = dict(row)
            out["plan"] = ensure_json_func(out.get("plan"))
            return out
    except Exception:
        return None

    return None


async def touch_cached_plan(
    cache_id: int,
    *,
    pg_fetchval_func: Optional[PgFetchVal] = None,
) -> None:
    try:
        if is_postgres():
            fetchval = pg_fetchval_func or pg_fetchval
            await fetchval(
                """
                UPDATE bi_meta.plan_cache
                SET hits = COALESCE(hits, 0) + 1,
                    last_used_at = now()
                WHERE id = $1
                RETURNING id;
                """,
                int(cache_id),
            )
            return

        if is_sqlserver():
            from backend.app.db.session import SessionLocal

            async with SessionLocal() as session:
                await session.execute(
                    text(
                        """
                        UPDATE bi_meta.plan_cache
                        SET hits = COALESCE(hits, 0) + 1,
                            last_used_at = SYSUTCDATETIME()
                        WHERE id = :cache_id;
                        """
                    ),
                    {"cache_id": int(cache_id)},
                )
                await session.commit()
    except Exception:
        pass


async def upsert_cached_plan(
    question_norm: str,
    question_raw: str,
    catalog_hash: str,
    plan: dict,
    model: str,
    *,
    pg_fetchval_func: Optional[PgFetchVal] = None,
) -> None:
    plan_json = json.dumps(plan, ensure_ascii=False)
    try:
        if is_postgres():
            fetchval = pg_fetchval_func or pg_fetchval
            await fetchval(
                """
                INSERT INTO bi_meta.plan_cache(question_norm, question_raw, catalog_hash, plan, model, hits, last_used_at)
                VALUES ($1, $2, $3, $4::jsonb, $5, 0, now())
                ON CONFLICT (question_norm, catalog_hash)
                DO UPDATE SET
                question_raw = EXCLUDED.question_raw,
                plan        = EXCLUDED.plan,
                model       = EXCLUDED.model,
                last_used_at = now(),
                updated_at  = CASE
                    WHEN bi_meta.plan_cache.plan  IS DISTINCT FROM EXCLUDED.plan
                        OR bi_meta.plan_cache.model IS DISTINCT FROM EXCLUDED.model
                    THEN now()
                    ELSE bi_meta.plan_cache.updated_at
                END;
                """,
                question_norm,
                question_raw,
                catalog_hash,
                plan_json,
                model,
            )
            return

        if is_sqlserver():
            from backend.app.db.session import SessionLocal

            params = {
                "question_norm": question_norm,
                "question_raw": question_raw,
                "catalog_hash": catalog_hash,
                "plan_json": plan_json,
                "model": model,
            }
            async with SessionLocal() as session:
                await session.execute(
                    text(
                        """
                        MERGE bi_meta.plan_cache WITH (HOLDLOCK) AS target
                        USING (
                            SELECT
                                :question_norm AS question_norm,
                                :question_raw AS question_raw,
                                :catalog_hash AS catalog_hash,
                                :plan_json AS [plan],
                                :model AS model
                        ) AS source
                        ON target.question_norm = source.question_norm
                           AND target.catalog_hash = source.catalog_hash
                        WHEN MATCHED THEN
                            UPDATE SET
                                question_raw = source.question_raw,
                                [plan] = source.[plan],
                                model = source.model,
                                last_used_at = SYSUTCDATETIME(),
                                updated_at = CASE
                                    WHEN ISNULL(target.[plan], N'') <> ISNULL(source.[plan], N'')
                                      OR ISNULL(target.model, N'') <> ISNULL(source.model, N'')
                                    THEN SYSUTCDATETIME()
                                    ELSE target.updated_at
                                END
                        WHEN NOT MATCHED THEN
                            INSERT (
                                question_norm, question_raw, catalog_hash,
                                [plan], model, hits, last_used_at
                            )
                            VALUES (
                                source.question_norm, source.question_raw,
                                source.catalog_hash, source.[plan],
                                source.model, 0, SYSUTCDATETIME()
                            );
                        """
                    ),
                    params,
                )
                await session.commit()
    except Exception:
        pass


async def insert_query_log(
    *,
    question: str,
    plan: dict,
    sql: str,
    row_count: int,
    warnings: list[str],
    suggestions: dict[str, Any],
    duration_ms: int,
    used_cache: bool,
    used_llm: bool,
    explain_used: bool,
    pg_fetchval_func: Optional[PgFetchVal] = None,
) -> Optional[int]:
    plan_json = json.dumps(plan, ensure_ascii=False)
    warnings_json = json.dumps(warnings, ensure_ascii=False)
    suggestions_json = json.dumps(suggestions, ensure_ascii=False)

    try:
        if is_postgres():
            fetchval = pg_fetchval_func or pg_fetchval
            log_id = await fetchval(
                """
                INSERT INTO bi_meta.query_log(
                    question, plan, sql, row_count, warnings, suggestions, duration_ms,
                    used_cache, used_llm, explain_used
                )
                VALUES ($1, $2::jsonb, $3, $4, $5::jsonb, $6::jsonb, $7, $8, $9, $10)
                RETURNING id;
                """,
                question,
                plan_json,
                sql,
                int(row_count),
                warnings_json,
                suggestions_json,
                int(duration_ms),
                bool(used_cache),
                bool(used_llm),
                bool(explain_used),
            )
            return int(log_id) if log_id is not None else None

        if is_sqlserver():
            from backend.app.db.session import SessionLocal

            async with SessionLocal() as session:
                result = await session.execute(
                    text(
                        """
                        INSERT INTO bi_meta.query_log(
                            question, [plan], [sql], row_count, warnings,
                            suggestions, duration_ms, used_cache, used_llm,
                            explain_used
                        )
                        OUTPUT INSERTED.id
                        VALUES (
                            :question, :plan_json, :sql, :row_count,
                            :warnings_json, :suggestions_json, :duration_ms,
                            :used_cache, :used_llm, :explain_used
                        );
                        """
                    ),
                    {
                        "question": question,
                        "plan_json": plan_json,
                        "sql": sql,
                        "row_count": int(row_count),
                        "warnings_json": warnings_json,
                        "suggestions_json": suggestions_json,
                        "duration_ms": int(duration_ms),
                        "used_cache": bool(used_cache),
                        "used_llm": bool(used_llm),
                        "explain_used": bool(explain_used),
                    },
                )
                log_id = result.scalar_one_or_none()
                await session.commit()
            return int(log_id) if log_id is not None else None
    except Exception:
        return None

    return None


__all__ = [
    "get_cached_plan",
    "touch_cached_plan",
    "upsert_cached_plan",
    "insert_query_log",
]
