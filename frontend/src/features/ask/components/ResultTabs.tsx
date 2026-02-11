import { useMemo, useState } from "react";
import type { AskResponse } from "../../../types/api";
import { ResultTable } from "./ResultTable";
import { CodePanel } from "./CodePanel";

type TabKey = "results" | "sql" | "plan" | "meta" | "explain";

export function ResultTabs({ data }: { data?: AskResponse }) {
  const [tab, setTab] = useState<TabKey>("results");

  const rows = data?.result?.rows ?? [];
  const sql = data?.result?.sql ?? "--";
  const plan = data?.plan ?? {};
  const meta = data?.meta ?? {};
  const explain = data?.explain;

  const planText = useMemo(() => JSON.stringify(plan, null, 2), [plan]);
  const metaText = useMemo(() => JSON.stringify(meta, null, 2), [meta]);

  const planCorrections: string[] = useMemo(() => {
    const arr = (meta as any)?.plan_corrections;
    return Array.isArray(arr) ? arr.filter((x) => typeof x === "string") : [];
  }, [meta]);

  const TabBtn = ({ k, label, icon }: { k: TabKey; label: string; icon: string }) => (
    <button
      type="button"
      className={`nav-link ${tab === k ? "active" : ""}`}
      onClick={() => setTab(k)}
      aria-current={tab === k ? "page" : undefined}
    >
      <i className={`bi ${icon} ms-2`} />
      {label}
    </button>
  );

  return (
    <>
      <ul className="nav nav-tabs mb-3">
        <li className="nav-item">
          <TabBtn k="results" label="النتائج" icon="bi-table" />
        </li>
        <li className="nav-item">
          <TabBtn k="sql" label="SQL" icon="bi-code-slash" />
        </li>
        <li className="nav-item">
          <TabBtn k="plan" label="Plan" icon="bi-diagram-3" />
        </li>
        <li className="nav-item">
          <TabBtn k="meta" label="Meta" icon="bi-info-circle" />
        </li>
        <li className="nav-item">
          <TabBtn k="explain" label="Explain" icon="bi-lightbulb" />
        </li>
      </ul>

      {tab === "results" && (
        <div className="tab-pane show active">
          {rows.length > 0 ? (
            <ResultTable rows={rows} />
          ) : (
            <div className="aac-card p-4 text-center text-secondary">
              <i className="bi bi-inbox mb-2" style={{ fontSize: 28 }} />
              <div className="fw-semibold">لا توجد نتائج</div>
              <div className="small mt-1">جرّب تعديل السؤال أو زيادة limit.</div>
            </div>
          )}
        </div>
      )}

      {tab === "sql" && (
        <div className="tab-pane show active aac-results-ltr">
          {/* ✅ نخلي CodePanel وحده تتحكم بالـ toolbar */}
          <CodePanel title="SQL" text={sql} kind="sql" />
        </div>
      )}

      {tab === "plan" && (
        <div className="tab-pane show active aac-results-ltr">
          <CodePanel title="Plan" text={planText} kind="json" />
        </div>
      )}

      {tab === "meta" && (
        <div className="tab-pane show active aac-results-ltr">
          <div className="vstack gap-3">
            <CodePanel title="Meta" text={metaText} kind="json" />

            <div className="aac-card p-3">
              <div className="d-flex align-items-center justify-content-between">
                <div className="fw-semibold">
                  <i className="bi bi-magic ms-2" />
                  Auto-fixes (plan_corrections)
                </div>
                <span className={`badge ${planCorrections.length ? "text-bg-info" : "text-bg-secondary"}`}>
                  {planCorrections.length}
                </span>
              </div>

              {planCorrections.length ? (
                <ul className="mb-0 mt-2 small lh-lg">
                  {planCorrections.map((x, i) => (
                    <li key={`${x}-${i}`}>
                      <code className="text-reset">{x}</code>
                    </li>
                  ))}
                </ul>
              ) : (
                <div className="text-secondary small mt-2">لا توجد تصحيحات تلقائية.</div>
              )}
            </div>
          </div>
        </div>
      )}

      {tab === "explain" && (
        <div className="tab-pane show active">
          {explain ? (
            <div className="vstack gap-3">
              {/* Summary */}
              <div className="aac-card p-3">
                <div className="d-flex align-items-center justify-content-between mb-2">
                  <div className="fw-semibold">
                    <i className="bi bi-lightbulb ms-2" />
                    Summary
                  </div>
                  <span className="badge text-bg-secondary">Explain</span>
                </div>

                <div className="row g-3">
                  <div className="col-12 col-lg-6" dir="rtl">
                    <div className="text-secondary small mb-1">Arabic</div>
                    <div className="lh-lg">{explain.summary_ar || "—"}</div>
                  </div>
                  <div className="col-12 col-lg-6" dir="ltr">
                    <div className="text-secondary small mb-1">English</div>
                    <div className="lh-lg">{explain.summary_en || "—"}</div>
                  </div>
                </div>
              </div>

              {/* Insights + Followups */}
              <div className="row g-3">
                <div className="col-12 col-lg-6">
                  <div className="aac-card p-3" dir="rtl">
                    <div className="fw-semibold mb-2">
                      <i className="bi bi-graph-up ms-2" />
                      Insights (AR)
                    </div>
                    {(explain.insights_ar?.length || 0) > 0 ? (
                      <ul className="mb-0 lh-lg">
                        {explain.insights_ar!.map((x: string, i: number) => (
                          <li key={i}>{x}</li>
                        ))}
                      </ul>
                    ) : (
                      <div className="text-secondary">—</div>
                    )}
                  </div>
                </div>

                <div className="col-12 col-lg-6">
                  <div className="aac-card p-3" dir="ltr">
                    <div className="fw-semibold mb-2">
                      <i className="bi bi-graph-up ms-2" />
                      Insights (EN)
                    </div>
                    {(explain.insights_en?.length || 0) > 0 ? (
                      <ul className="mb-0 lh-lg">
                        {explain.insights_en!.map((x: string, i: number) => (
                          <li key={i}>{x}</li>
                        ))}
                      </ul>
                    ) : (
                      <div className="text-secondary">—</div>
                    )}
                  </div>
                </div>

                <div className="col-12 col-lg-6">
                  <div className="aac-card p-3" dir="rtl">
                    <div className="fw-semibold mb-2">
                      <i className="bi bi-question-circle ms-2" />
                      Followups (AR)
                    </div>
                    {(explain.followups_ar?.length || 0) > 0 ? (
                      <ul className="mb-0 lh-lg">
                        {explain.followups_ar!.map((x: string, i: number) => (
                          <li key={i}>{x}</li>
                        ))}
                      </ul>
                    ) : (
                      <div className="text-secondary">—</div>
                    )}
                  </div>
                </div>

                <div className="col-12 col-lg-6">
                  <div className="aac-card p-3" dir="ltr">
                    <div className="fw-semibold mb-2">
                      <i className="bi bi-question-circle ms-2" />
                      Followups (EN)
                    </div>
                    {(explain.followups_en?.length || 0) > 0 ? (
                      <ul className="mb-0 lh-lg">
                        {explain.followups_en!.map((x: string, i: number) => (
                          <li key={i}>{x}</li>
                        ))}
                      </ul>
                    ) : (
                      <div className="text-secondary">—</div>
                    )}
                  </div>
                </div>
              </div>
            </div>
          ) : (
            <div className="text-secondary">فعّل Explain من Settings.</div>
          )}
        </div>
      )}
    </>
  );
}
