import React, { useEffect, useMemo, useState } from "react";
import { toPng } from "html-to-image";
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
} from "recharts";

type ChartType = "bar" | "bar_stacked" | "line";
type Agg = "sum" | "avg" | "count" | "min" | "max";

const SERIES_COLORS = [
  "rgb(var(--bs-primary-rgb))",
  "rgb(var(--bs-info-rgb))",
  "rgb(var(--bs-success-rgb))",
  "rgb(var(--bs-warning-rgb))",
  "rgb(var(--bs-danger-rgb))",
  "rgb(var(--bs-secondary-rgb))",
];

const LS_PREFIX = "aac_viz_v1_";
const LS_VERSION = 1;

type VizSettings = {
  v: number;
  chartType: ChartType;
  xField: string;
  yField: string;
  groupField: string;
  aggType: Agg;
  topN: number;
};

function fnv1a32(str: string): string {
  let h = 0x811c9dc5;
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return (h >>> 0).toString(16).padStart(8, "0");
}

function safeJsonParse<T>(s: string | null): T | null {
  if (!s) return null;
  try {
    return JSON.parse(s) as T;
  } catch {
    return null;
  }
}

function safeLocalStorageGet(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}
function safeLocalStorageSet(key: string, value: string) {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // ignore
  }
}
function safeLocalStorageRemove(key: string) {
  try {
    window.localStorage.removeItem(key);
  } catch {
    // ignore
  }
}
function safeLocalStorageClearPrefix(prefix: string) {
  try {
    const keys: string[] = [];
    for (let i = 0; i < window.localStorage.length; i++) {
      const k = window.localStorage.key(i);
      if (k && k.startsWith(prefix)) keys.push(k);
    }
    keys.forEach((k) => window.localStorage.removeItem(k));
  } catch {
    // ignore
  }
}

function clampInt(n: any, min: number, max: number, fallback: number) {
  const x = Number(n);
  if (!Number.isFinite(x)) return fallback;
  return Math.max(min, Math.min(max, Math.floor(x)));
}

function toNumber(v: any): number | null {
  if (v === null || v === undefined) return null;
  if (typeof v === "number" && Number.isFinite(v)) return v;
  if (typeof v === "string") {
    const s = v.trim().replace(/,/g, "");
    if (!s) return null;
    const n = Number(s);
    return Number.isFinite(n) ? n : null;
  }
  return null;
}

function inferNumeric(cols: string[], rows: any[]) {
  const sample = rows.slice(0, 50);
  const numeric: string[] = [];
  const other: string[] = [];

  for (const c of cols) {
    let seen = 0;
    let hits = 0;
    for (const r of sample) {
      const v = r?.[c];
      if (v === null || v === undefined || v === "") continue;
      seen++;
      if (toNumber(v) !== null) hits++;
    }
    if (seen > 0 && hits / seen >= 0.6) numeric.push(c);
    else other.push(c);
  }
  return { numeric, other, xCandidates: [...other, ...numeric] };
}

function looksTimeLike(col: string) {
  const c = (col || "").toLowerCase();
  return (
    c.includes("date") ||
    c.includes("month") ||
    c.includes("year") ||
    c.includes("quarter") ||
    c.includes("week") ||
    c.includes("day")
  );
}

function normalizeChartType(x: any): ChartType {
  if (x === "bar" || x === "bar_stacked" || x === "line") return x;
  return "bar";
}

const nf = new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 });

function parseTimeKey(v: any): number | null {
  if (v === null || v === undefined) return null;
  if (typeof v === "number" && Number.isFinite(v)) return v;

  const s = String(v).trim();

  // YYYY
  const mY = s.match(/^(\d{4})$/);
  if (mY) return Number(mY[1]) * 1000000;

  // YYYY-QN or YYYY QN
  const mQ = s.match(/^(\d{4})\s*[-_/ ]\s*Q([1-4])$/i);
  if (mQ) return Number(mQ[1]) * 1000000 + Number(mQ[2]) * 10000;

  // YYYY-MM or YYYY/MM
  const mYM = s.match(/^(\d{4})\s*[-_/]\s*(\d{1,2})$/);
  if (mYM) return Number(mYM[1]) * 1000000 + Number(mYM[2]) * 10000;

  // ISO date-ish: try Date.parse
  const t = Date.parse(s);
  if (!Number.isNaN(t)) return t;

  return null;
}

function inferSmartDefaults(args: {
  rows: any[];
  columns: string[];
  numeric: string[];
  xCandidates: string[];
}) {
  const { columns, numeric, xCandidates } = args;

  const nonNumeric = columns.filter((c) => !numeric.includes(c));
  const x =
    nonNumeric.find(looksTimeLike) ||
    nonNumeric[0] ||
    xCandidates[0] ||
    columns[0] ||
    "";

  const y =
    numeric.find((c) => {
      const k = c.toLowerCase();
      return (
        k.includes("net_sales") ||
        k.includes("sales") ||
        k.includes("revenue") ||
        k.includes("amount") ||
        k.includes("profit")
      );
    }) ||
    numeric[0] ||
    "";

  const group =
    nonNumeric.find((c) => c !== x && !looksTimeLike(c)) || "";

  const isTimeX = looksTimeLike(x);
  const chartType: ChartType = isTimeX ? "line" : "bar";

  return {
    chartType,
    xField: x,
    yField: y,
    groupField: group,
    aggType: "sum" as Agg,
    topN: 10,
  };
}

function aggregate(
  rows: any[],
  xField: string,
  yField: string | "",
  groupField: string | "",
  agg: Agg,
  topN: number,
  preferChronoX: boolean
) {
  type Bucket = { x: any; g: any; count: number; sum: number; min: number; max: number };
  const map = new Map<string, Bucket>();

  for (const r of rows) {
    const x = r?.[xField];
    const g = groupField ? r?.[groupField] : null;
    const key = `${String(x)}||${String(g)}`;

    let b = map.get(key);
    if (!b) {
      b = { x, g, count: 0, sum: 0, min: Infinity, max: -Infinity };
      map.set(key, b);
    }

    b.count += 1;

    if (agg !== "count") {
      const n = yField ? toNumber(r?.[yField]) : null;
      if (n !== null) {
        b.sum += n;
        b.min = Math.min(b.min, n);
        b.max = Math.max(b.max, n);
      }
    }
  }

  const flat = Array.from(map.values()).map((b) => {
    let value = 0;
    if (agg === "count") value = b.count;
    else if (agg === "sum") value = b.sum;
    else if (agg === "avg") value = b.count ? b.sum / b.count : 0;
    else if (agg === "min") value = b.min === Infinity ? 0 : b.min;
    else value = b.max === -Infinity ? 0 : b.max;

    return { x: b.x, group: b.g, value };
  });

  const totals = new Map<string, number>();
  for (const r of flat) totals.set(String(r.x), (totals.get(String(r.x)) ?? 0) + (r.value ?? 0));

  // choose topX by totals desc, then order later depending on preferChronoX
  const topX = Array.from(totals.entries())
    .sort((a, b) => b[1] - a[1])
    .slice(0, Math.max(1, topN))
    .map(([x]) => x);

  const filtered = flat.filter((r) => topX.includes(String(r.x)));

  const series = Array.from(new Set(filtered.map((r) => String(r.group)))).filter((s) => s !== "null");

  const byX = new Map<string, any>();
  for (const r of filtered) {
    const k = String(r.x);
    const obj = byX.get(k) ?? { x: r.x };
    if (r.group === null || r.group === undefined) obj.value = r.value;
    else obj[String(r.group)] = r.value;
    byX.set(k, obj);
  }

  let data = Array.from(byX.values());

  // Order data
  if (preferChronoX) {
    data = data
      .map((d) => ({ ...d, __tk: parseTimeKey(d.x) }))
      .sort((a, b) => {
        const ta = a.__tk;
        const tb = b.__tk;
        if (ta === null && tb === null) return String(a.x).localeCompare(String(b.x));
        if (ta === null) return 1;
        if (tb === null) return -1;
        return ta - tb;
      })
      .map(({ __tk, ...rest }) => rest);
  } else {
    // keep top totals order
    const order = new Map<string, number>();
    topX.forEach((k, i) => order.set(String(k), i));
    data.sort((a, b) => (order.get(String(a.x)) ?? 1e9) - (order.get(String(b.x)) ?? 1e9));
  }

  return { data, series };
}

export function VizTab(props: { rows: any[]; columns: string[]; sql?: string }) {
  const { rows, columns, sql } = props;

  const { numeric, xCandidates } = useMemo(() => inferNumeric(columns, rows), [columns, rows]);

  const storageKey = useMemo(() => {
    const base = (sql && sql.trim() !== "" ? sql.trim() : JSON.stringify(columns || [])) || "empty";
    return `${LS_PREFIX}${fnv1a32(base)}`;
  }, [sql, columns]);

  const [touched, setTouched] = useState({
    chartType: false,
    xField: false,
    yField: false,
    groupField: false,
    aggType: false,
    topN: false,
  });

  const smartDefault = useMemo(() => {
    return inferSmartDefaults({ rows, columns, numeric, xCandidates });
  }, [rows, columns, numeric, xCandidates]);

  const [chartType, setChartType] = useState<ChartType>(smartDefault.chartType);
  const [xField, setXField] = useState<string>(smartDefault.xField);
  const [yField, setYField] = useState<string>(smartDefault.yField);
  const [groupField, setGroupField] = useState<string>(smartDefault.groupField);
  const [aggType, setAggType] = useState<Agg>(smartDefault.aggType);
  const [topN, setTopN] = useState<number>(smartDefault.topN);

  const chartRef = React.useRef<HTMLDivElement | null>(null);
  const loadedRef = React.useRef<string | null>(null);

  const hasGroup = !!groupField;
  const preferChronoX = looksTimeLike(xField);

  function applyDefaultsSmart() {
    setTouched({
      chartType: false,
      xField: false,
      yField: false,
      groupField: false,
      aggType: false,
      topN: false,
    });

    // if group exists, stacked bar is usually better (unless time-like X => line)
    const defaultChart: ChartType =
      looksTimeLike(smartDefault.xField) ? "line" : (smartDefault.groupField ? "bar_stacked" : smartDefault.chartType);

    setChartType(defaultChart);
    setAggType(smartDefault.aggType);
    setTopN(smartDefault.topN);
    setGroupField(smartDefault.groupField);
    setXField(smartDefault.xField);
    setYField(smartDefault.yField);
  }

  function touch<K extends keyof typeof touched>(k: K) {
    setTouched((t) => ({ ...t, [k]: true }));
  }

  // Load saved settings
  useEffect(() => {
    loadedRef.current = null;

    const raw = safeLocalStorageGet(storageKey);
    const saved = safeJsonParse<VizSettings>(raw);

    if (!saved || saved.v !== LS_VERSION) {
      loadedRef.current = storageKey;
      return;
    }

    const xOk = saved.xField && xCandidates.includes(saved.xField);
    const yOk = saved.yField && numeric.includes(saved.yField);
    const gOk = !saved.groupField || columns.includes(saved.groupField);

    const ct = normalizeChartType(saved.chartType);

    setChartType(ct);
    setAggType((saved.aggType ?? smartDefault.aggType) as Agg);
    setTopN(clampInt(saved.topN, 1, 200, smartDefault.topN));

    setXField(xOk ? saved.xField : smartDefault.xField);
    setYField(yOk ? saved.yField : smartDefault.yField);
    setGroupField(gOk ? saved.groupField : "");

    setTouched({
      chartType: true,
      xField: true,
      yField: true,
      groupField: true,
      aggType: true,
      topN: true,
    });

    loadedRef.current = storageKey;
  }, [storageKey, xCandidates, numeric, columns, smartDefault]);

  // Smart defaults on result change (respect touched)
  useEffect(() => {
    if (!rows || rows.length === 0) return;

    // prefer stacked when group exists and not time-like X
    const suggestedChart: ChartType =
      looksTimeLike(smartDefault.xField) ? "line" : (smartDefault.groupField ? "bar_stacked" : smartDefault.chartType);

    if (!touched.chartType) setChartType(suggestedChart);
    if (!touched.xField) setXField(smartDefault.xField);
    if (!touched.yField) setYField(smartDefault.yField);
    if (!touched.groupField) setGroupField(smartDefault.groupField);
    if (!touched.aggType) setAggType(smartDefault.aggType);
    if (!touched.topN) setTopN(smartDefault.topN);
  }, [rows, smartDefault, touched]);

  // Keep fields valid
  useEffect(() => {
    setXField((prev) => (prev && xCandidates.includes(prev) ? prev : smartDefault.xField));
  }, [xCandidates, smartDefault.xField]);

  useEffect(() => {
    setYField((prev) => (prev && numeric.includes(prev) ? prev : smartDefault.yField));
  }, [numeric, smartDefault.yField]);

  useEffect(() => {
    setGroupField((prev) => (prev && columns.includes(prev) ? prev : ""));
  }, [columns]);

  // If chartType is stacked but no group => downgrade to bar
  useEffect(() => {
    if (chartType === "bar_stacked" && !hasGroup) {
      setChartType("bar");
    }
  }, [chartType, hasGroup]);

  // Save settings (after load)
  useEffect(() => {
    if (loadedRef.current !== storageKey) return;

    const payload: VizSettings = {
      v: LS_VERSION,
      chartType,
      xField,
      yField,
      groupField,
      aggType,
      topN: clampInt(topN, 1, 200, 10),
    };

    safeLocalStorageSet(storageKey, JSON.stringify(payload));
  }, [storageKey, chartType, xField, yField, groupField, aggType, topN]);

  const canRender =
    rows.length > 0 &&
    xField &&
    (aggType === "count" ? true : !!yField && numeric.includes(yField));

  const prepared = useMemo(() => {
    if (!canRender) return { data: [], series: [] as string[] };
    return aggregate(
      rows,
      xField,
      yField,
      groupField,
      aggType,
      clampInt(topN, 1, 200, 10),
      preferChronoX
    );
  }, [rows, xField, yField, groupField, aggType, topN, canRender, preferChronoX]);

  const yTickFormatter = (v: any) => {
    const n = toNumber(v);
    return n === null ? String(v ?? "") : nf.format(n);
  };

  return (
    <div className="viz-tab" dir="ltr">
      <div className="d-flex flex-wrap gap-2 align-items-end mb-3">
        <div>
          <label className="form-label mb-1">Chart</label>
          <select
            className="form-select form-select-sm"
            value={chartType}
            onChange={(e) => {
              touch("chartType");
              setChartType(e.target.value as ChartType);
            }}
          >
            <option value="bar">Bar</option>
            <option value="bar_stacked" disabled={!hasGroup}>
              Stacked Bar
            </option>
            <option value="line">Line</option>
          </select>
        </div>

        <div>
          <label className="form-label mb-1">X</label>
          <select
            className="form-select form-select-sm"
            value={xField}
            onChange={(e) => {
              touch("xField");
              setXField(e.target.value);
            }}
          >
            {xCandidates.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label className="form-label mb-1">Y</label>
          <select
            className="form-select form-select-sm"
            value={yField}
            onChange={(e) => {
              touch("yField");
              setYField(e.target.value);
            }}
            disabled={aggType === "count"}
          >
            {numeric.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label className="form-label mb-1">Group (optional)</label>
          <select
            className="form-select form-select-sm"
            value={groupField}
            onChange={(e) => {
              touch("groupField");
              setGroupField(e.target.value);
            }}
          >
            <option value="">(none)</option>
            {columns
              .filter((c) => c !== xField && c !== yField)
              .map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
          </select>
        </div>

        <div>
          <label className="form-label mb-1">Agg</label>
          <select
            className="form-select form-select-sm"
            value={aggType}
            onChange={(e) => {
              touch("aggType");
              setAggType(e.target.value as Agg);
            }}
          >
            <option value="sum">sum</option>
            <option value="avg">avg</option>
            <option value="count">count</option>
            <option value="min">min</option>
            <option value="max">max</option>
          </select>
        </div>

        <div style={{ width: 110 }}>
          <label className="form-label mb-1">Top N</label>
          <input
            className="form-control form-control-sm"
            type="number"
            min={1}
            max={200}
            value={topN}
            onChange={(e) => {
              touch("topN");
              setTopN(clampInt(e.target.value, 1, 200, 10));
            }}
          />
        </div>
      </div>

      {!rows.length ? (
        <div className="text-body-secondary">No rows to visualize.</div>
      ) : !canRender ? (
        <div className="text-body-secondary">Pick X/Y (or use count) to render.</div>
      ) : (
        <>
          <div className="d-flex justify-content-end gap-2 mb-2">
            <button
              type="button"
              className="btn btn-sm btn-outline-secondary"
              onClick={applyDefaultsSmart}
              title="Reset to smart defaults"
            >
              <i className="bi bi-magic ms-2" />
              Smart reset
            </button>

            <button
              type="button"
              className="btn btn-sm btn-outline-secondary"
              onClick={() => {
                safeLocalStorageRemove(storageKey);
                applyDefaultsSmart();
              }}
              title="Clear saved settings for this query"
            >
              <i className="bi bi-eraser ms-2" />
              Clear saved
            </button>

            <button
              type="button"
              className="btn btn-sm btn-outline-secondary"
              onClick={() => {
                safeLocalStorageClearPrefix(LS_PREFIX);
                applyDefaultsSmart();
              }}
              title="Clear ALL saved chart settings"
            >
              <i className="bi bi-trash3 ms-2" />
              Clear all
            </button>

            <button
              type="button"
              className="btn btn-sm btn-outline-secondary"
              onClick={async () => {
                if (!chartRef.current) return;
                try {
                  const dataUrl = await toPng(chartRef.current, { cacheBust: true, pixelRatio: 2 });
                  const a = document.createElement("a");
                  a.href = dataUrl;
                  a.download = "aac_chart.png";
                  a.click();
                } catch {
                  // ignore
                }
              }}
              title="Export chart as PNG"
            >
              <i className="bi bi-download ms-2" />
              Export PNG
            </button>
          </div>

          <div className="border rounded p-2" ref={chartRef}>
            <ResponsiveContainer width="100%" height={380}>
              {chartType === "line" ? (
                <LineChart data={prepared.data}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="x" />
                  <YAxis tickFormatter={yTickFormatter} />
                  <Tooltip formatter={(v: any) => yTickFormatter(v)} />
                  <Legend />
                  {prepared.series.length ? (
                    prepared.series.map((s, i) => (
                      <Line
                        key={s}
                        type="monotone"
                        dataKey={s}
                        dot={false}
                        stroke={SERIES_COLORS[i % SERIES_COLORS.length]}
                      />
                    ))
                  ) : (
                    <Line type="monotone" dataKey="value" dot={false} stroke={SERIES_COLORS[0]} />
                  )}
                </LineChart>
              ) : (
                <BarChart data={prepared.data}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="x" />
                  <YAxis tickFormatter={yTickFormatter} />
                  <Tooltip formatter={(v: any) => yTickFormatter(v)} />
                  <Legend />
                  {prepared.series.length ? (
                    prepared.series.map((s, i) => (
                      <Bar
                        key={s}
                        dataKey={s}
                        fill={SERIES_COLORS[i % SERIES_COLORS.length]}
                        stackId={chartType === "bar_stacked" ? "a" : undefined}
                      />
                    ))
                  ) : (
                    <Bar dataKey="value" fill={SERIES_COLORS[0]} />
                  )}
                </BarChart>
              )}
            </ResponsiveContainer>
          </div>
        </>
      )}
    </div>
  );
}
