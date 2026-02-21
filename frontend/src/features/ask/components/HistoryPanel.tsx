// frontend/src/features/ask/components/HistoryPanel.tsx
import { useMemo, useState } from "react";
import { useAskStore } from "../../../store/useAskStore";
import { formatTime } from "../../../utils/time";

export function HistoryPanel() {
  const { history, clearHistory, setDraftQuestion, requestFocus, runAsk, busy } = useAskStore();
  const [q, setQ] = useState("");

  const filtered = useMemo(() => {
    const s = q.trim();
    if (!s) return history;
    return history.filter((h) => (h?.q || "").includes(s));
  }, [history, q]);

  const top = filtered.slice(0, 50);

  const load = (h: any) => {
    if (!h?.q) return;
    setDraftQuestion(h.q);
    requestFocus();
  };

  const run = (h: any) => {
    if (!h?.q) return;
    load(h);
    runAsk(h.q, h.req);
  };

  return (
    <div className="d-flex flex-column h-100" style={{ minHeight: 0 }}>
      <div className="d-flex justify-content-between align-items-center mb-2">
        <div className="fw-semibold">
          History <span className="badge text-bg-secondary ms-2">{history.length}</span>
        </div>

        <button
          className="btn btn-outline-danger btn-sm"
          onClick={clearHistory}
          title="Clear"
          disabled={history.length === 0}
          type="button"
        >
          <i className="bi bi-trash3" />
        </button>
      </div>

      <input
        className="form-control form-control-sm mb-2"
        placeholder="بحث في السجل..."
        value={q}
        onChange={(e) => setQ(e.target.value)}
      />

      {/* ✅ Scroll area */}
      <div className="aac-history-scroll vstack gap-2 flex-grow-1" style={{ minHeight: 0 }}>
        {top.length === 0 && <div className="text-secondary small">لا يوجد سجل.</div>}

        {top.map((h: any, i: number) => {
          const m = h?.meta || {};

          // Only show the "LLM" badge when the LLM actually succeeded.
          const usedLlm = !!m.used_llm;
          const usedCache = m.used_cache;

          // ✅ show TOTAL if available, fallback to duration_ms
          const ms =
            typeof m.total_ms === "number"
              ? m.total_ms
              : typeof m.duration_ms === "number"
                ? m.duration_ms
                : undefined;

          const llmStatus = typeof m.llm_status === "string" ? m.llm_status : undefined;
          const llmMs = typeof m.llm_ms === "number" ? m.llm_ms : undefined;

          const llmOk = llmStatus === "ok" || llmStatus === "mock";
          const llmTone = "text-bg-success";

          return (
            <div
              key={i}
              className="aac-card p-2"
              role="button"
              tabIndex={0}
              onClick={() => load(h)}
              onKeyDown={(e) => {
                if (e.key === "Enter") load(h);
              }}
              style={{ cursor: "pointer" }}
              title={h.q}
            >
              <div className="aac-history-item">
                {/* Question */}
                <div className="flex-grow-1">
                  <div
                    dir="rtl"
                    className="aac-history-q"
                    style={{
                      display: "-webkit-box",
                      WebkitLineClamp: 3,
                      WebkitBoxOrient: "vertical",
                      overflow: "hidden",
                      whiteSpace: "normal",
                    }}
                  >
                    {h.q}
                  </div>

                  <div className="d-flex flex-wrap gap-1 mt-2 align-items-center">
                    <span className="badge text-bg-secondary mono">
                      <i className="bi bi-clock ms-1" />
                      {formatTime(h.ts)}
                    </span>

                    {typeof ms === "number" && (
                      <span className="badge text-bg-secondary">TOTAL {ms}ms</span>
                    )}

                    {typeof usedCache === "boolean" && (
                      <span className={`badge ${usedCache ? "text-bg-success" : "text-bg-secondary"}`}>
                        Cache
                      </span>
                    )}

                    {/* LLM badge: show only on success */}
                    {llmOk ? (
                      <span className={`badge ${llmTone}`} title={typeof llmMs === "number" ? `LLM ${llmMs}ms` : undefined}>
                        LLM
                      </span>
                    ) : null}
                  </div>
                </div>

                {/* Run button */}
                <div className="aac-history-run">
                  <button
                    type="button"
                    className="btn btn-outline-primary btn-sm"
                    onClick={(e) => {
                      e.stopPropagation();
                      run(h);
                    }}
                    disabled={busy}
                    title="تشغيل"
                  >
                    <i className="bi bi-play-fill" />
                  </button>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {busy && <div className="text-secondary small mt-2">جاري التنفيذ…</div>}
    </div>
  );
}
