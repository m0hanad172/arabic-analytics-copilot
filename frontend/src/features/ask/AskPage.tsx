// frontend/src/features/ask/AskPage.tsx
import { useCallback } from "react";
import { useAskStore } from "../../store/useAskStore";
import { QuestionEditor } from "./components/QuestionEditor";
import { ResultTabs } from "./components/ResultTabs";
import { MetaBadges } from "./components/MetaBadges";

export function AskPage() {
  const { busy, error, last, runAsk } = useAskStore();

  // If we have usable output (rows or SQL) then an LLM timeout/error is a soft failure
  // because the backend can fall back to rule-based planning.
  const hasOutput =
    (last?.result?.rows?.length ?? 0) > 0 ||
    (!!last?.result?.sql && last?.result?.sql !== "--");

  // Only show a big warning if the LLM error prevented producing output.
  const showHardLlmError = !!last?.meta?.llm_error && !hasOutput;

  const run = useCallback(() => {
    runAsk();
  }, [runAsk]);

  return (
    <div className="vstack gap-3">
      <div className="aac-card p-3">
        <div className="d-flex flex-wrap align-items-center justify-content-between gap-2 mb-2">
          <div className="fw-semibold">
            <i className="bi bi-chat-square-text" /> Ask
          </div>
          <MetaBadges meta={last?.meta} />
        </div>

        <QuestionEditor busy={busy} onRun={run} />

        {error && (
          <div className="alert alert-danger mt-3 mb-0">
            <div className="fw-semibold mb-1">
              <i className="bi bi-x-octagon" /> Error
            </div>
            <div className="mono small">{error}</div>
          </div>
        )}

        {showHardLlmError && (
          <div className="alert alert-warning mt-3 mb-0">
            <div className="fw-semibold mb-1">
              <i className="bi bi-exclamation-triangle" /> LLM Error
            </div>
            <div className="mono small">{String(last.meta.llm_error)}</div>
          </div>
        )}
      </div>

      <div className="aac-card p-3">
        <ResultTabs data={last} />
      </div>
    </div>
  );
}
