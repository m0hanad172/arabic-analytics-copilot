import { useMemo, useState } from "react";
import type { ReactNode } from "react";
import type { AskResponse } from "../../../types/api";
import { ResultTable } from "./ResultTable";
import { CodePanel } from "./CodePanel";
import { VizTab } from "./VizTab";
import { useAskStore } from "../../../store/useAskStore";

type TabKey = "results" | "sql" | "plan" | "meta" | "explain" | "viz";

function asString(v: any): string {
  if (v === null || v === undefined) return "";
  if (typeof v === "string") return v;
  try {
    return JSON.stringify(v, null, 2);
  } catch {
    return String(v);
  }
}

function asList(v: any): string[] {
  if (!v) return [];
  if (Array.isArray(v)) return v.map(String).map((s) => s.trim()).filter(Boolean);
  if (typeof v === "string") {
    return v
      .split("\n")
      .map((s) => s.trim())
      .filter(Boolean);
  }
  return [];
}

function extractKeys(v: any): string[] {
  if (!v) return [];
  if (Array.isArray(v)) {
    return v
      .map((it) => {
        if (typeof it === "string") return it;
        if (it && typeof it === "object") {
          return it.key ?? it.name ?? it.metric_key ?? it.dim_key ?? it.field ?? it.id ?? "";
        }
        return String(it);
      })
      .map((s) => String(s).trim())
      .filter(Boolean);
  }
  if (typeof v === "string") {
    return v
      .split(/[,\n]/g)
      .map((s) => s.trim())
      .filter(Boolean);
  }
  return [];
}

function formatSort(sortVal: any): string {
  const arr = Array.isArray(sortVal) ? sortVal : sortVal ? [sortVal] : [];
  const parts = arr
    .map((s: any) => {
      if (!s) return "";
      if (typeof s === "string") return s.trim();
      if (typeof s === "object") {
        const f = (s.field ?? s.column ?? s.key ?? "").toString().trim();
        const d = (s.dir ?? s.direction ?? "").toString().trim().toLowerCase();
        if (!f) return "";
        return d ? `${f} ${d}` : f;
      }
      return "";
    })
    .filter(Boolean);

  return parts.length ? parts.join("، ") : "—";
}

function formatFilters(filtersVal: any): string {
  const arr = Array.isArray(filtersVal) ? filtersVal : filtersVal ? [filtersVal] : [];
  const parts = arr
    .map((f: any) => {
      if (!f) return "";
      if (typeof f === "string") return f.trim();

      if (typeof f === "object") {
        const field = (f.field ?? f.column ?? f.key ?? "").toString().trim();
        const op = (f.op ?? f.operator ?? "").toString().trim();
        const value = f.value;

        if (!field) return "";

        let vStr = "";
        if (value === null || value === undefined) vStr = "";
        else if (Array.isArray(value)) vStr = value.map((x) => String(x)).join("، ");
        else if (typeof value === "object") {
          try {
            vStr = JSON.stringify(value);
          } catch {
            vStr = String(value);
          }
        } else vStr = String(value);

        return op ? `${field} ${op} ${vStr}`.trim() : `${field} ${vStr}`.trim();
      }

      return "";
    })
    .filter(Boolean);

  return parts.length ? parts.join(" ؛ ") : "—";
}

function normalizeExplain(explain: any) {
  const enObj = explain?.en ?? {};
  const arObj = explain?.ar ?? {};

  const legacySummaryEn = explain?.summary_en ?? explain?.text_en ?? "";
  const legacySummaryAr = explain?.summary_ar ?? explain?.text_ar ?? "";

  const legacyInsightsEn = explain?.insights_en;
  const legacyInsightsAr = explain?.insights_ar;
  const legacyFollowupsEn = explain?.followups_en;
  const legacyFollowupsAr = explain?.followups_ar;

  return {
    en: {
      summary: asString(enObj.summary ?? legacySummaryEn),
      insights: asList(enObj.insights ?? legacyInsightsEn),
      followups: asList(enObj.followups ?? legacyFollowupsEn),
    },
    ar: {
      summary: asString(arObj.summary ?? legacySummaryAr),
      insights: asList(arObj.insights ?? legacyInsightsAr),
      followups: asList(arObj.followups ?? legacyFollowupsAr),
    },
  };
}

type Line = { k: string; v: string };

function SummaryLines({ lines, dir }: { lines: Line[]; dir: "rtl" | "ltr" }) {
  const isRtl = dir === "rtl";

  return (
    <div className="vstack gap-2" dir={dir}>
      {lines.map((x, i) => (
        <div
          key={`${x.k}-${i}`}
          style={{
            display: "flex",
            alignItems: "baseline",
            gap: "0.75rem",
            justifyContent: isRtl ? "flex-end" : "flex-start",
            direction: isRtl ? "rtl" : "ltr",
          }}
        >
          <div
            className="text-secondary small"
            style={{
              flex: "0 0 auto",
              whiteSpace: "nowrap",
              textAlign: isRtl ? "right" : "left",
            }}
            title={x.k}
          >
            {x.k}
          </div>

          <div
            dir="auto"
            style={{
              flex: "0 1 70%",
              maxWidth: "100%",
              minWidth: 0,
              whiteSpace: "pre-wrap",
              textAlign: isRtl ? "right" : "left",
              unicodeBidi: "plaintext",
            }}
          >
            {x.v || "—"}
          </div>
        </div>
      ))}
    </div>
  );
}

// -------------------------
// ✅ Copy helpers (non-breaking)
// -------------------------
async function copyToClipboard(text: string): Promise<boolean> {
  const t = (text ?? "").toString();
  if (!t) return false;

  try {
    if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(t);
      return true;
    }
  } catch {
    // fallthrough
  }

  try {
    const ta = document.createElement("textarea");
    ta.value = t;
    ta.setAttribute("readonly", "");
    ta.style.position = "fixed";
    ta.style.left = "-9999px";
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(ta);
    return ok;
  } catch {
    return false;
  }
}

function CopyBtn({ text, title = "نسخ" }: { text: string; title?: string }) {
  const [copied, setCopied] = useState(false);

  return (
    <button
      type="button"
      className={`btn btn-sm ${copied ? "btn-success" : "btn-outline-secondary"}`}
      onClick={async () => {
        const ok = await copyToClipboard(text);
        if (!ok) return;
        setCopied(true);
        window.setTimeout(() => setCopied(false), 900);
      }}
      title={title}
      style={{ lineHeight: 1 }}
    >
      <i className={`bi ${copied ? "bi-check2" : "bi-clipboard"} ms-2`} />
      {copied ? "تم" : "نسخ"}
    </button>
  );
}

function StatBadge({ text, variant }: { text: string; variant: string }) {
  return (
    <span className={`badge ${variant}`} style={{ fontWeight: 600 }}>
      {text}
    </span>
  );
}

function FieldBlock(props: {
  label: string;
  children: ReactNode;
  hint?: string;
  ltrValue?: boolean;
  copyText?: string;
  copyTitle?: string;
}) {
  const { label, children, hint, ltrValue, copyText, copyTitle } = props;
  return (
    <div className="aac-card p-3">
      <div className="d-flex align-items-center justify-content-between mb-2">
        <div className="fw-semibold">{label}</div>

        <div className="d-flex align-items-center gap-2">
          {hint ? <div className="text-secondary small">{hint}</div> : null}
          {copyText ? <CopyBtn text={copyText} title={copyTitle ?? `نسخ ${label}`} /> : null}
        </div>
      </div>

      <div className={ltrValue ? "aac-ltr" : ""} dir={ltrValue ? "ltr" : "rtl"} style={{ unicodeBidi: "plaintext" }}>
        {children}
      </div>
    </div>
  );
}

// ✅ Badges with collapse (non-breaking)
function BadgesList({ items, max = 8 }: { items: string[]; max?: number }) {
  const [expanded, setExpanded] = useState(false);

  if (!items?.length) return <div className="text-secondary">—</div>;

  const overflow = items.length > max;
  const shown = overflow && !expanded ? items.slice(0, max) : items;

  return (
    <div className="d-flex flex-wrap gap-2 align-items-center">
      {shown.map((x, i) => (
        <span key={`${x}-${i}`} className="badge text-bg-secondary" style={{ fontWeight: 600 }}>
          <code className="text-reset" dir="ltr">
            {x}
          </code>
        </span>
      ))}

      {overflow ? (
        <button
          type="button"
          className="btn btn-sm btn-outline-secondary"
          onClick={() => setExpanded((v) => !v)}
          title={expanded ? "إخفاء" : "عرض الكل"}
        >
          {expanded ? "إخفاء" : `+${items.length - max}`}
        </button>
      ) : null}
    </div>
  );
}

export function ResultTabs({
  data,
  onUseQuestion,
}: {
  data?: AskResponse;
  onUseQuestion?: (q: string) => void;
}) {
  const [tab, setTab] = useState<TabKey>("results");

  // ✅ fallback to store (non-breaking if you don't pass onUseQuestion)
  const setDraftQuestion = useAskStore((s: any) => s.setDraftQuestion);
  const bumpFocusTick = useAskStore((s: any) => s.bumpFocusTick);
  const setFocusTick = useAskStore((s: any) => s.setFocusTick);

  const focusEditor = () => {
    if (typeof bumpFocusTick === "function") bumpFocusTick();
    else if (typeof setFocusTick === "function") setFocusTick(Date.now());
  };

  const handleUseQuestion = (q: string) => {
    const qq = (q ?? "").toString().trim();
    if (!qq) return;

    if (typeof onUseQuestion === "function") onUseQuestion(qq);
    else if (typeof setDraftQuestion === "function") setDraftQuestion(qq);

    focusEditor();
  };

  const rows = data?.result?.rows ?? [];
  const columns = useMemo(() => (rows[0] ? Object.keys(rows[0]) : []), [rows]);
  const sql = data?.result?.sql ?? "--";
  const plan: any = data?.plan ?? {};
  const meta: any = data?.meta ?? {};
  const explainRaw: any = (data as any)?.explain;

  const planText = useMemo(() => JSON.stringify(plan, null, 2), [plan]);
  const metaText = useMemo(() => JSON.stringify(meta, null, 2), [meta]);

  const planCorrections: string[] = useMemo(() => {
    const arr = meta?.plan_corrections;
    return Array.isArray(arr) ? arr.filter((x) => typeof x === "string") : [];
  }, [meta]);

  const explain = useMemo(() => normalizeExplain(explainRaw), [explainRaw]);

  const hasExplainPayload =
    !!explainRaw &&
    (explain.ar.summary || explain.ar.insights.length > 0 || explain.ar.followups.length > 0);

  const summaryLines = useMemo(() => {
    const originalQuestion = (data as any)?.question ?? "";
    const metrics = extractKeys(plan?.metrics);
    const dims = extractKeys(plan?.dimensions);
    const filters = formatFilters(plan?.filters);
    const sort = formatSort(plan?.sort);
    const rowCount = rows.length;

    const limitNum = Number.isFinite(Number(plan?.limit)) ? Number(plan?.limit) : undefined;
    const rowsLineAr = limitNum ? `${rowCount} (الحد ${limitNum})` : String(rowCount || 0);

    const notesRaw = (plan?.notes ?? plan?.note ?? "").toString().trim();
    const notesAr =
      (notesRaw ? notesRaw : "—") +
      (planCorrections.length ? ` | التصحيحات: ${planCorrections.join("، ")}` : "");

    const ar: Line[] = [
      { k: "السؤال", v: originalQuestion || "—" },
      { k: "الأبعاد", v: dims.length ? dims.join("، ") : "—" },
      { k: "المقاييس", v: metrics.length ? metrics.join("، ") : "—" },
      { k: "الفلاتر", v: filters || "—" },
      { k: "الترتيب", v: sort || "—" },
      { k: "عدد الصفوف", v: rowsLineAr },
      { k: "ملاحظة", v: notesAr },
    ];

    return { ar };
  }, [data, plan, rows.length, planCorrections]);

  const planView = useMemo(() => {
    const metrics = extractKeys(plan?.metrics);
    const dims = extractKeys(plan?.dimensions);

    const filtersRaw = formatFilters(plan?.filters);
    const filters = filtersRaw === "—" ? "لا يوجد" : filtersRaw;

    const sort = formatSort(plan?.sort);

    const limitNum = Number.isFinite(Number(plan?.limit)) ? Number(plan?.limit) : null;
    const notes = (plan?.notes ?? plan?.note ?? "").toString().trim();

    return {
      metrics,
      dims,
      filters,
      sort,
      limitNum,
      notes: notes || "—",
    };
  }, [plan]);

  const usedLlm = !!meta?.used_llm;
  const usedCache = !!meta?.used_cache;
  const rowCount = rows.length;

  const [showPlanJson, setShowPlanJson] = useState(false);

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
          <TabBtn k="plan" label="الخطة" icon="bi-diagram-3" />
        </li>
        <li className="nav-item">
          <TabBtn k="meta" label="بيانات التشغيل" icon="bi-info-circle" />
        </li>
        <li className="nav-item">
          <TabBtn k="explain" label="الشرح" icon="bi-lightbulb" />
        </li>
        <li className="nav-item">
          <TabBtn k="viz" label="الرسوم" icon="bi-bar-chart" />
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
          <CodePanel title="SQL" text={sql} kind="sql" />
        </div>
      )}

      {tab === "plan" && (
        <div className="tab-pane show active aac-rtl" dir="rtl">
          <div className="vstack gap-3">
            <div className="aac-card p-3">
              <div className="d-flex flex-wrap align-items-center justify-content-between gap-2 mb-3">
                <div className="fw-semibold">
                  <i className="bi bi-diagram-3 ms-2" />
                  ملخص الخطة
                </div>

                <div className="d-flex flex-wrap align-items-center gap-2">
                  <StatBadge
                    text={usedLlm ? "مصدر الخطة: LLM" : "مصدر الخطة: قواعد"}
                    variant={usedLlm ? "text-bg-success" : "text-bg-secondary"}
                  />
                  <StatBadge text={usedCache ? "Cache: HIT" : "Cache: MISS"} variant={usedCache ? "text-bg-info" : "text-bg-secondary"} />
                  <StatBadge text={`Rows: ${rowCount}`} variant="text-bg-secondary" />
                  {planView.limitNum !== null ? <StatBadge text={`Limit: ${planView.limitNum}`} variant="text-bg-secondary" /> : null}

                  <CopyBtn text={planText} title="نسخ الخطة (JSON)" />

                  <button
                    type="button"
                    className="btn btn-sm btn-outline-secondary"
                    onClick={() => setShowPlanJson((v) => !v)}
                    title="عرض/إخفاء JSON"
                  >
                    <i className="bi bi-braces ms-2" />
                    {showPlanJson ? "إخفاء JSON" : "عرض JSON"}
                  </button>
                </div>
              </div>

              <div className="row g-3">
                <div className="col-12 col-lg-6">
                  <FieldBlock
                    label="الأبعاد"
                    hint={`${planView.dims.length}`}
                    copyText={planView.dims.join(", ")}
                    copyTitle="نسخ الأبعاد"
                  >
                    <BadgesList items={planView.dims} />
                  </FieldBlock>
                </div>

                <div className="col-12 col-lg-6">
                  <FieldBlock
                    label="المقاييس"
                    hint={`${planView.metrics.length}`}
                    copyText={planView.metrics.join(", ")}
                    copyTitle="نسخ المقاييس"
                  >
                    <BadgesList items={planView.metrics} />
                  </FieldBlock>
                </div>

                <div className="col-12 col-lg-6">
                  <FieldBlock label="الفلاتر" copyText={planView.filters} copyTitle="نسخ الفلاتر">
                    <div style={{ unicodeBidi: "plaintext" }}>{planView.filters || "—"}</div>
                  </FieldBlock>
                </div>

                <div className="col-12 col-lg-6">
                  <FieldBlock label="الترتيب" copyText={planView.sort} copyTitle="نسخ الترتيب">
                    <div style={{ unicodeBidi: "plaintext" }}>{planView.sort || "—"}</div>
                  </FieldBlock>
                </div>

                <div className="col-12 col-lg-4">
                  <FieldBlock
                    label="الحد (Limit)"
                    copyText={planView.limitNum !== null ? String(planView.limitNum) : "—"}
                    copyTitle="نسخ الحد"
                  >
                    <div className="fw-semibold">{planView.limitNum !== null ? planView.limitNum : "—"}</div>
                  </FieldBlock>
                </div>

                <div className="col-12 col-lg-8">
                  <FieldBlock label="ملاحظات" copyText={planView.notes} copyTitle="نسخ الملاحظات">
                    <div style={{ whiteSpace: "pre-wrap", unicodeBidi: "plaintext" }}>{planView.notes}</div>
                  </FieldBlock>
                </div>
              </div>
            </div>

            {showPlanJson && (
              <div className="aac-ltr" dir="ltr">
                <CodePanel title="الخطة (JSON)" text={planText} kind="json" />
              </div>
            )}
          </div>
        </div>
      )}

      {tab === "meta" && (
        <div className="tab-pane show active aac-rtl">
          <div className="vstack gap-3">
            <div className="aac-ltr" dir="ltr">
              <CodePanel title="Meta" text={metaText} kind="json" />
            </div>

            <div className="aac-card p-3">
              <div className="d-flex align-items-center justify-content-between">
                <div className="fw-semibold">
                  <i className="bi bi-magic ms-2" />
                  التصحيحات التلقائية <span className="text-secondary">(plan_corrections)</span>
                </div>

                <span className={`badge ${planCorrections.length ? "text-bg-info" : "text-bg-secondary"}`}>
                  {planCorrections.length}
                </span>
              </div>

              {planCorrections.length ? (
                <div className="d-flex flex-wrap gap-2 mt-2 aac-ltr" dir="ltr">
                  {planCorrections.map((x, i) => (
                    <span key={`${x}-${i}`} className="badge text-bg-info">
                      <code className="text-reset">{x}</code>
                    </span>
                  ))}
                </div>
              ) : (
                <div className="text-secondary small mt-2">لا توجد تصحيحات تلقائية.</div>
              )}
            </div>
          </div>
        </div>
      )}

      {tab === "explain" && (
        <div className="tab-pane show active aac-rtl">
          {hasExplainPayload ? (
            <div className="vstack gap-3">
              <div className="aac-card p-3" dir="rtl">
                <div className="d-flex align-items-center justify-content-between mb-2">
                  <div className="fw-semibold">
                    <i className="bi bi-lightbulb ms-2" />
                    الملخص
                  </div>
                  <span className="badge text-bg-secondary">Explain</span>
                </div>

                <SummaryLines lines={summaryLines.ar} dir="rtl" />
              </div>

              <div className="row g-3">
                <div className="col-12 col-lg-6">
                  <div className="aac-card p-3" dir="rtl">
                    <div className="fw-semibold mb-2">
                      <i className="bi bi-graph-up ms-2" />
                      ملاحظات
                    </div>
                    {explain.ar.insights.length ? (
                      <ul className="mb-0 lh-lg" style={{ paddingRight: "1.25rem" }}>
                        {explain.ar.insights.map((x, i) => (
                          <li key={i} style={{ unicodeBidi: "plaintext" }}>
                            {x}
                          </li>
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
                      اقتراحات متابعة
                    </div>

                    {explain.ar.followups.length ? (
                      <ul className="mb-0 lh-lg" style={{ paddingRight: "1.25rem" }}>
                        {explain.ar.followups.map((x, i) => (
                          <li key={i} className="d-flex align-items-start justify-content-between gap-2">
                            <span style={{ unicodeBidi: "plaintext" }}>{x}</span>
                            <div className="d-flex gap-2 flex-shrink-0">
                              <button
                                type="button"
                                className="btn btn-sm btn-outline-secondary"
                                onClick={() => handleUseQuestion(x)}
                                title="استخدام هذا الاقتراح كسؤال"
                              >
                                <i className="bi bi-arrow-return-left ms-2" />
                                استخدم
                              </button>
                              <CopyBtn text={x} title="نسخ الاقتراح" />
                            </div>
                          </li>
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
            <div className="aac-card p-4 text-secondary">
              <div className="fw-semibold mb-1">الشرح غير متوفر</div>
              <div className="small">
                فعّل Explain من Settings، وتأكد أن طلب /api/ask يحتوي <code>explain=1</code>.
              </div>
            </div>
          )}
        </div>
      )}

      {tab === "viz" && (
        <div className="tab-pane show active aac-results-ltr">
          <VizTab rows={rows} columns={columns} sql={sql} />
        </div>
      )}
    </>
  );
}
