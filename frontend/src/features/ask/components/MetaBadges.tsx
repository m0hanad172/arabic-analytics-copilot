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

  // --- LLM badge (product mode)
  // Only show "LLM" when it actually succeeded. If it failed but we fell back,
  // keep the header clean; details remain in the Meta tab.
  const llmStatus = typeof meta.llm_status === "string" ? meta.llm_status : undefined;
  const llmOk = llmStatus === "ok" || llmStatus === "mock";

  // --- Timing (TOTAL / DB / LLM)
  const totalMs =
    typeof meta.total_ms === "number"
      ? meta.total_ms
      : typeof meta.duration_ms === "number"
        ? meta.duration_ms
        : undefined;

  const dbMs = typeof meta.duration_ms === "number" ? meta.duration_ms : undefined;
  const llmMs = typeof meta.llm_ms === "number" ? meta.llm_ms : undefined;

  // Keep errors inside Meta tab only.
  const llmErrorTitle = undefined;

  return (
    <div className="d-flex flex-column gap-2">
      <div className="d-flex flex-wrap gap-2 align-items-center">
        <span className={`badge ${meta.used_cache ? "text-bg-success" : "text-bg-secondary"}`}>
          {cacheLabel}
        </span>

        {llmOk ? (
          <span className="badge text-bg-success" title={llmErrorTitle}>LLM</span>
        ) : null}

        {/* ✅ TOTAL (wall time) */}
        {typeof totalMs === "number" && (
          <span className="badge text-bg-secondary">TOTAL {totalMs}ms</span>
        )}

        {/* Optional: DB time */}
        {typeof dbMs === "number" && (
          <span className="badge text-bg-secondary">DB {dbMs}ms</span>
        )}

        {/* Optional: LLM time (only when succeeded) */}
        {llmOk && typeof llmMs === "number" ? (
          <span className="badge text-bg-secondary">LLM {llmMs}ms</span>
        ) : null}

        <span className={`badge ${fixes.length ? "text-bg-info" : "text-bg-secondary"}`}>
          FIXES: {fixes.length}
        </span>

        {meta.ask_version && (
          <span className="badge text-bg-secondary">{meta.ask_version}</span>
        )}

        {meta.log_id != null && (
          <span className="badge text-bg-secondary">LOG #{meta.log_id}</span>
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
    </div>
  );
}
