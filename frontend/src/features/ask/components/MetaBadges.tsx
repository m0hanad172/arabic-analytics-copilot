// frontend/src/features/ask/components/MetaBadges.tsx
import { useMemo } from "react";
import type { AskMeta } from "../../../types/api";

export function MetaBadges({ meta }: { meta?: AskMeta | null }) {
  const fixes = useMemo(() => {
    const arr = meta?.plan_corrections ?? [];
    return Array.isArray(arr) ? arr : [];
  }, [meta]);

  if (!meta) return null;

  const cacheLabel = meta.used_cache ? "CACHE: HIT" : "CACHE: MISS";
  const llmLabel = !meta.llm_enabled
    ? "LLM: DISABLED"
    : meta.used_llm
      ? "LLM: USED"
      : meta.llm_attempted
        ? "LLM: FAILED"
        : "LLM: NOT USED";

  const llmTone =
    !meta.llm_enabled ? "text-bg-secondary" :
    meta.used_llm ? "text-bg-success" :
    meta.llm_attempted ? "text-bg-warning" :
    "text-bg-secondary";

  return (
    <div className="d-flex flex-column gap-2">
      <div className="d-flex flex-wrap gap-2 align-items-center">
        <span className={`badge ${meta.used_cache ? "text-bg-success" : "text-bg-secondary"}`}>
          {cacheLabel}
        </span>

        <span className={`badge ${llmTone}`}>
          {llmLabel}
        </span>

        {typeof meta.duration_ms === "number" && (
          <span className="badge text-bg-secondary">
            {meta.duration_ms} ms
          </span>
        )}

        <span className={`badge ${fixes.length ? "text-bg-info" : "text-bg-secondary"}`}>
          FIXES: {fixes.length}
        </span>

        {meta.ask_version && (
          <span className="badge text-bg-secondary">
            {meta.ask_version}
          </span>
        )}

        {meta.log_id != null && (
          <span className="badge text-bg-secondary">
            LOG #{meta.log_id}
          </span>
        )}
      </div>

      {/* تفاصيل الإصلاحات */}
      {fixes.length > 0 && (
        <details className="small">
          <summary className="text-muted" style={{ cursor: "pointer" }}>
            View auto-fixes
          </summary>
          <ul className="mt-2 mb-0">
            {fixes.map((x, i) => (
              <li key={`${x}-${i}`} className="text-muted">
                <code className="text-reset">{x}</code>
              </li>
            ))}
          </ul>
        </details>
      )}

      {/* خطأ LLM لو موجود */}
      {meta.llm_attempted && meta.llm_error && (
        <div className="small text-warning">
          <strong>LLM error:</strong> <code className="text-reset">{meta.llm_error}</code>
        </div>
      )}
    </div>
  );
}
