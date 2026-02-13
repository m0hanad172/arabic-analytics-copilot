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

type ChartType = "bar" | "line";
type Agg = "sum" | "avg" | "count" | "min" | "max";

const SERIES_COLORS = [
  "rgb(var(--bs-primary-rgb))",
  "rgb(var(--bs-info-rgb))",
  "rgb(var(--bs-success-rgb))",
  "rgb(var(--bs-warning-rgb))",
  "rgb(var(--bs-danger-rgb))",
  "rgb(var(--bs-secondary-rgb))",
];

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

function aggregate(
  rows: any[],
  xField: string,
  yField: string | "",
  groupField: string | "",
  agg: Agg,
  topN: number
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

  // Top N by total per x (حتى لو grouped)
  const totals = new Map<string, number>();
  for (const r of flat) totals.set(String(r.x), (totals.get(String(r.x)) ?? 0) + (r.value ?? 0));

  const topX = Array.from(totals.entries())
    .sort((a, b) => b[1] - a[1])
    .slice(0, Math.max(1, topN))
    .map(([x]) => x);

  const filtered = flat.filter((r) => topX.includes(String(r.x)));

  // Pivot to {x, series1: v, series2: v}
  const series = Array.from(new Set(filtered.map((r) => String(r.group)))).filter((s) => s !== "null");

  const byX = new Map<string, any>();
  for (const r of filtered) {
    const k = String(r.x);
    const obj = byX.get(k) ?? { x: r.x };
    if (r.group === null || r.group === undefined) obj.value = r.value;
    else obj[String(r.group)] = r.value;
    byX.set(k, obj);
  }

  return { data: Array.from(byX.values()), series };
}

export function VizTab(props: { rows: any[]; columns: string[] }) {
  const { rows, columns } = props;

  const { numeric, xCandidates } = useMemo(() => inferNumeric(columns, rows), [columns, rows]);

  const [chartType, setChartType] = useState<ChartType>("bar");
  const [xField, setXField] = useState<string>(xCandidates[0] ?? "");
  const [yField, setYField] = useState<string>(numeric[0] ?? "");
  const [groupField, setGroupField] = useState<string>("");
  const [aggType, setAggType] = useState<Agg>("sum");
  const [topN, setTopN] = useState<number>(10);

  const chartRef = React.useRef<HTMLDivElement | null>(null);

  // ✅ Auto-suggest (non-breaking): only if empty/invalid after results change
  useEffect(() => {
    if (!xCandidates.length) return;
    setXField((prev) => (prev && xCandidates.includes(prev) ? prev : xCandidates[0]));
  }, [xCandidates]);

  useEffect(() => {
    if (!numeric.length) return;
    setYField((prev) => (prev && numeric.includes(prev) ? prev : numeric[0]));
  }, [numeric]);

  useEffect(() => {
    setGroupField((prev) => (prev && columns.includes(prev) ? prev : ""));
  }, [columns]);

  const canRender =
    rows.length > 0 &&
    xField &&
    (aggType === "count" ? true : !!yField && numeric.includes(yField));

  const prepared = useMemo(() => {
    if (!canRender) return { data: [], series: [] as string[] };
    return aggregate(rows, xField, yField, groupField, aggType, topN);
  }, [rows, xField, yField, groupField, aggType, topN, canRender]);

  return (
    <div className="viz-tab" dir="ltr">
      <div className="d-flex flex-wrap gap-2 align-items-end mb-3">
        <div>
          <label className="form-label mb-1">Chart</label>
          <select
            className="form-select form-select-sm"
            value={chartType}
            onChange={(e) => setChartType(e.target.value as ChartType)}
          >
            <option value="bar">Bar</option>
            <option value="line">Line</option>
          </select>
        </div>

        <div>
          <label className="form-label mb-1">X</label>
          <select className="form-select form-select-sm" value={xField} onChange={(e) => setXField(e.target.value)}>
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
            onChange={(e) => setYField(e.target.value)}
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
          <select className="form-select form-select-sm" value={groupField} onChange={(e) => setGroupField(e.target.value)}>
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
          <select className="form-select form-select-sm" value={aggType} onChange={(e) => setAggType(e.target.value as Agg)}>
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
            onChange={(e) => setTopN(Number(e.target.value || 10))}
          />
        </div>
      </div>

      {!rows.length ? (
        <div className="text-body-secondary">No rows to visualize.</div>
      ) : !canRender ? (
        <div className="text-body-secondary">Pick X/Y (or use count) to render.</div>
      ) : (
        <>
          <div className="d-flex justify-content-end mb-2">
            <button
              type="button"
              className="btn btn-sm btn-outline-secondary"
              onClick={async () => {
                if (!chartRef.current) return;
                const dataUrl = await toPng(chartRef.current, { cacheBust: true, pixelRatio: 2 });
                const a = document.createElement("a");
                a.href = dataUrl;
                a.download = "aac_chart.png";
                a.click();
              }}
            >
              <i className="bi bi-download ms-2" />
              Export PNG
            </button>
          </div>

          <div className="border rounded p-2" ref={chartRef}>
            <ResponsiveContainer width="100%" height={380}>
              {chartType === "bar" ? (
                <BarChart data={prepared.data}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="x" />
                  <YAxis />
                  <Tooltip />
                  <Legend />
                  {prepared.series.length
                    ? prepared.series.map((s, i) => (
                        <Bar key={s} dataKey={s} fill={SERIES_COLORS[i % SERIES_COLORS.length]} />
                      ))
                    : <Bar dataKey="value" fill={SERIES_COLORS[0]} />}
                </BarChart>
              ) : (
                <LineChart data={prepared.data}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="x" />
                  <YAxis />
                  <Tooltip />
                  <Legend />
                  {prepared.series.length
                    ? prepared.series.map((s, i) => (
                        <Line
                          key={s}
                          type="monotone"
                          dataKey={s}
                          dot={false}
                          stroke={SERIES_COLORS[i % SERIES_COLORS.length]}
                        />
                      ))
                    : (
                      <Line
                        type="monotone"
                        dataKey="value"
                        dot={false}
                        stroke={SERIES_COLORS[0]}
                      />
                    )}
                </LineChart>
              )}
            </ResponsiveContainer>
          </div>
        </>
      )}
    </div>
  );
}
