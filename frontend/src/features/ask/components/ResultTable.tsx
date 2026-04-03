import { useEffect, useMemo, useRef, useState } from "react";
import {
  getCoreRowModel,
  getFilteredRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useReactTable,
} from "@tanstack/react-table";

import type {
  ColumnDef,
  ColumnFiltersState,
  FilterFn,
  SortingState,
  VisibilityState,
  RowSelectionState,
} from "@tanstack/react-table";

import { rankItem } from "@tanstack/match-sorter-utils";

type RowObj = Record<string, any>;

function buildColumns(rows: RowObj[]) {
  const objs = (rows || []).filter((r) => r && typeof r === "object");
  if (!objs.length) return [];
  const keys = Object.keys(objs[0]);
  const seen = new Set(keys);

  for (const r of objs.slice(1, 100)) {
    for (const k of Object.keys(r)) {
      if (!seen.has(k)) {
        seen.add(k);
        keys.push(k);
      }
    }
  }
  return keys;
}

function isNumberLike(v: any) {
  if (v === null || v === undefined) return false;
  if (typeof v === "number") return Number.isFinite(v);
  if (typeof v === "string") {
    const n = Number(v.trim().replace(/,/g, ""));
    return Number.isFinite(n);
  }
  return false;
}

function toNumber(v: any) {
  if (typeof v === "number") return v;
  if (typeof v === "string") return Number(v.trim().replace(/,/g, ""));
  return NaN;
}

function normalizeDigits(s: string) {
  const map: Record<string, string> = {
    "٠": "0",
    "١": "1",
    "٢": "2",
    "٣": "3",
    "٤": "4",
    "٥": "5",
    "٦": "6",
    "٧": "7",
    "٨": "8",
    "٩": "9",
  };
  return s.replace(/[٠-٩]/g, (d) => map[d] ?? d);
}

function parseNumInput(raw: string): number | null {
  const s = normalizeDigits(String(raw ?? ""))
    .trim()
    .replace(/,/g, "")
    .replace(/\s+/g, "");
  if (!s) return null;
  const n = Number(s);
  return Number.isFinite(n) ? n : null;
}

const fuzzyFilter: FilterFn<RowObj> = (row, columnId, value, addMeta) => {
  const itemRank = rankItem(String(row.getValue(columnId) ?? ""), String(value ?? ""));
  addMeta({ itemRank });
  return itemRank.passed;
};

const numRangeFilter: FilterFn<RowObj> = (row, columnId, value) => {
  const n = toNumber(row.getValue<any>(columnId));
  if (!Number.isFinite(n)) return false;

  const [minRaw, maxRaw] = (value as [string, string]) || ["", ""];
  const minN = parseNumInput(minRaw);
  const maxN = parseNumInput(maxRaw);

  if (minN !== null && n < minN) return false;
  if (maxN !== null && n > maxN) return false;
  return true;
};

function escapeCsv(v: any) {
  const s = String(v ?? "");
  if (/[",\n]/.test(s)) return `"${s.replace(/"/g, '""')}"`;
  return s;
}

function downloadCsv(filename: string, cols: string[], rows: RowObj[]) {
  const header = cols.map(escapeCsv).join(",");
  const lines = rows.map((r) => cols.map((c) => escapeCsv(r?.[c])).join(","));
  const csv = [header, ...lines].join("\n");
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export function ResultTable({ rows }: { rows: any[] }) {
  const data: RowObj[] = useMemo(() => (rows || []).filter(Boolean), [rows]);
  const colKeys = useMemo(() => buildColumns(data), [data]);

  const numericCols = useMemo(() => {
    const out: Record<string, boolean> = {};
    const sample = data.slice(0, 50);
    for (const c of colKeys) {
      let hits = 0;
      let total = 0;
      for (const r of sample) {
        const v = r?.[c];
        if (v === null || v === undefined || v === "") continue;
        total++;
        if (isNumberLike(v)) hits++;
      }
      out[c] = total > 0 ? hits / total >= 0.85 : false;
    }
    return out;
  }, [data, colKeys]);

  // NEW: row selection state
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({});

  // NEW: selection column (checkbox)
  const selectionCol = useMemo<ColumnDef<RowObj, unknown>>(
    () => ({
      id: "__select",
      header: ({ table }) => {
        // select all FILTERED rows (not just current page)
        const isAll = table.getIsAllRowsSelected();
        const isSome = table.getIsSomeRowsSelected();

        return (
          <div className="d-flex align-items-center justify-content-center" title="Select all">
            <input
              type="checkbox"
              className="form-check-input m-0"
              checked={isAll}
              ref={(el) => {
                if (el) el.indeterminate = !isAll && isSome;
              }}
              onChange={table.getToggleAllRowsSelectedHandler()}
              onClick={(e) => e.stopPropagation()}
            />
          </div>
        );
      },
      cell: ({ row }) => (
        <div className="d-flex align-items-center justify-content-center">
          <input
            type="checkbox"
            className="form-check-input m-0"
            checked={row.getIsSelected()}
            disabled={!row.getCanSelect()}
            onChange={row.getToggleSelectedHandler()}
            onClick={(e) => e.stopPropagation()}
            aria-label="Select row"
          />
        </div>
      ),
      enableSorting: false,
      enableColumnFilter: false,
      size: 42,
      minSize: 42,
      maxSize: 42,
    }),
    []
  );

  const columns = useMemo<ColumnDef<RowObj, unknown>[]>(() => {
    const dataCols = colKeys.map((key) => {
      const isNum = !!numericCols[key];

      const col: ColumnDef<RowObj, unknown> = {
        accessorKey: key,
        header: key,
        // مهم: لا تستخدم toLocaleString عشان "2016" ما تصير "2,016"
        cell: ({ getValue }) => {
          const v = getValue<any>();
          const text = v === null || v === undefined || v === "" ? "—" : String(v);
          return (
            <span className="aac-cell" style={{ display: "block", width: "100%", textAlign: "left" }}>
              {text}
            </span>
          );
        },
        enableColumnFilter: true,
        filterFn: isNum ? numRangeFilter : fuzzyFilter,
        sortingFn: isNum ? "basic" : "alphanumeric",
      };

      return col;
    });

    // prepend checkbox column without changing your columns logic
    return [selectionCol, ...dataCols];
  }, [colKeys, numericCols, selectionCol]);

  const [globalFilter, setGlobalFilter] = useState("");
  const [sorting, setSorting] = useState<SortingState>([]);
  const [columnFilters, setColumnFilters] = useState<ColumnFiltersState>([]);
  const [columnVisibility, setColumnVisibility] = useState<VisibilityState>({});
  const [showFilters, setShowFilters] = useState(false);

  const filterRefs = useRef<Record<string, HTMLInputElement | null>>({});

  const table = useReactTable({
    data,
    columns,

    state: { sorting, globalFilter, columnFilters, columnVisibility, rowSelection },
    onSortingChange: setSorting,
    onGlobalFilterChange: setGlobalFilter,
    onColumnFiltersChange: setColumnFilters,
    onColumnVisibilityChange: setColumnVisibility,

    onRowSelectionChange: setRowSelection,
    enableRowSelection: true,

    filterFns: { fuzzy: fuzzyFilter, numRange: numRangeFilter },
    globalFilterFn: fuzzyFilter,

    getCoreRowModel: getCoreRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getPaginationRowModel: getPaginationRowModel(),

    initialState: {
      pagination: { pageSize: 10, pageIndex: 0 },
    },
  });

  // default sort: first numeric column desc
  const isTimeLikeCol = (k: string) =>
  /(^|_)(year|quarter|month|day|date)$/i.test(k) ||
  /^order_(year|quarter|month|day)$/i.test(k);

useEffect(() => {
  if (sorting.length) return;

  const yearCol =
    colKeys.find((k) => k === "order_year") ||
    colKeys.find((k) => /(^|_)year$/i.test(k));

  const metricCol = colKeys.find((k) => numericCols[k] && !isTimeLikeCol(k));

  // إذا عندنا سنة + مقياس: خلي العرض طبيعي (زمني ثم مقياس)
  if (yearCol && metricCol) {
    setSorting([
      { id: yearCol, desc: false },      // year ASC
      { id: metricCol, desc: true },     // metric DESC داخل السنة
    ]);
    return;
  }

  // fallback: أول عمود رقمي غير زمني DESC
  if (metricCol) setSorting([{ id: metricCol, desc: true }]);
}, [colKeys, numericCols, sorting.length]);

  const filteredRowCount = table.getFilteredRowModel().rows.length;
  const totalRowCount = table.getCoreRowModel().rows.length;
  const selectedRowCount = table.getSelectedRowModel().rows.length;

  if (!data.length) return <div className="text-secondary">No rows.</div>;

  const leafCols = table.getVisibleLeafColumns();
  const visibleCols = leafCols
    .map((c) => c.id)
    //  do not export the checkbox column
    .filter((id) => id !== "__select");

  const clearAllFilters = () => {
    setGlobalFilter("");
    setColumnFilters([]);
  };

  const exportFilteredCsv = () => {
    const rowsNow = table.getFilteredRowModel().rows.map((r) => r.original);
    downloadCsv("results_filtered.csv", visibleCols, rowsNow);
  };

  const exportSelectedCsv = () => {
    const rowsNow = table.getSelectedRowModel().rows.map((r) => r.original);
    downloadCsv("results_selected.csv", visibleCols, rowsNow);
  };

  const clearSelection = () => setRowSelection({});

  return (
    <div className="aac-results-ltr" dir="ltr">
      {/* Toolbar */}
      <div className="d-flex flex-wrap gap-2 align-items-center justify-content-between mb-2">
        <div className="d-flex flex-wrap gap-2 align-items-center">
          <div className="input-group" style={{ minWidth: 320 }}>
            <span className="input-group-text">
              <i className="bi bi-search" />
            </span>
            <input
              className="form-control"
              placeholder="Search in results…"
              value={globalFilter ?? ""}
              onChange={(e) => setGlobalFilter(e.target.value)}
            />
            {globalFilter ? (
              <button className="btn btn-outline-secondary" onClick={() => setGlobalFilter("")} title="Clear">
                <i className="bi bi-x-lg" />
              </button>
            ) : null}
          </div>

          <button
            className={`btn btn-outline-secondary ${showFilters ? "active" : ""}`}
            onClick={() => setShowFilters((v) => !v)}
            title="Column Filters"
          >
            <i className="bi bi-funnel me-1" />
            Column filters
          </button>

          <button className="btn btn-outline-warning" onClick={clearAllFilters} title="Clear all filters">
            <i className="bi bi-eraser me-1" />
            Clear filters
          </button>

          <div className="dropdown">
            <button className="btn btn-outline-secondary dropdown-toggle" data-bs-toggle="dropdown">
              <i className="bi bi-layout-three-columns me-1" />
              Columns
            </button>
            <div className="dropdown-menu p-2" style={{ minWidth: 260 }}>
              <div className="small text-secondary mb-2">Show / hide columns</div>
              {table.getAllLeafColumns().map((col) => {
                //  hide checkbox column from this menu
                if (col.id === "__select") return null;

                return (
                  <label key={col.id} className="dropdown-item d-flex align-items-center gap-2">
                    <input
                      type="checkbox"
                      className="form-check-input m-0"
                      checked={col.getIsVisible()}
                      onChange={col.getToggleVisibilityHandler()}
                    />
                    <span className="text-truncate">{col.id}</span>
                  </label>
                );
              })}
            </div>
          </div>

          <button className="btn btn-outline-secondary" onClick={exportFilteredCsv} title="Export CSV (Filtered)">
            <i className="bi bi-download me-1" />
            CSV
          </button>

          <button
            className="btn btn-outline-secondary"
            onClick={exportSelectedCsv}
            title="Export CSV (Selected)"
            disabled={selectedRowCount === 0}
          >
            <i className="bi bi-check2-square me-1" />
            CSV Selected
          </button>

          <button
            className="btn btn-outline-secondary"
            onClick={clearSelection}
            title="Clear selection"
            disabled={selectedRowCount === 0}
          >
            <i className="bi bi-x-square me-1" />
            Clear Selected
          </button>
        </div>

        <div className="d-flex gap-2 align-items-center text-secondary small">
          <span>
            Showing {filteredRowCount.toLocaleString()} / {totalRowCount.toLocaleString()}
          </span>
          <span className="opacity-50">|</span>
          <span>Selected {selectedRowCount.toLocaleString()}</span>
          <span className="opacity-50">|</span>
          <span>
            Page {table.getState().pagination.pageIndex + 1} / {table.getPageCount()}
          </span>
        </div>
      </div>

      {/* Table */}
      <div className="table-responsive" dir="ltr">
        <table className="table table-sm table-hover align-middle mb-0" dir="ltr">
          <thead>
            <tr>
              {leafCols.map((col) => {
                // special header for checkbox column (no sort/filter buttons)
                if (col.id === "__select") {
                  return (
                    <th
                      key={col.id}
                      className="text-nowrap"
                      style={{ textAlign: "center", width: 42 }}
                    >
                      {typeof col.columnDef.header === "function"
                        ? col.columnDef.header({ table } as any)
                        : null}
                    </th>
                  );
                }

                const sorted = col.getIsSorted();
                const isFiltered = col.getIsFiltered();
                const label =
                  typeof col.columnDef.header === "string" ? col.columnDef.header : col.id;

                const openFilter = (e: React.MouseEvent) => {
                  e.preventDefault();
                  e.stopPropagation();
                  setShowFilters(true);
                  setTimeout(() => filterRefs.current[col.id]?.focus(), 50);
                };

                return (
                  <th key={col.id} className="text-nowrap" style={{ textAlign: "left" }}>
                    <div className="d-flex align-items-center justify-content-between gap-2">
                      <button
                        type="button"
                        className="btn btn-link p-0 text-reset text-decoration-none d-inline-flex align-items-center gap-2"
                        onClick={col.getToggleSortingHandler()}
                      >
                        <span className="fw-semibold">{label}</span>
                        <span className="opacity-75">
                          {sorted === "asc" && <i className="bi bi-sort-up" />}
                          {sorted === "desc" && <i className="bi bi-sort-down" />}
                          {!sorted && <i className="bi bi-arrow-down-up opacity-50" />}
                        </span>
                      </button>

                      <button
                        type="button"
                        className={`btn btn-outline-secondary btn-sm ${isFiltered ? "active" : ""}`}
                        onClick={openFilter}
                        title="Filter"
                      >
                        <i className={`bi ${isFiltered ? "bi-funnel-fill" : "bi-funnel"}`} />
                      </button>
                    </div>
                  </th>
                );
              })}
            </tr>

            {showFilters && (
              <tr>
                {leafCols.map((col) => {
                  const id = col.id;

                  // no filter cell for checkbox column
                  if (id === "__select") return <th key={id} />;

                  const isNum = !!numericCols[id];

                  if (isNum) {
                    const val = (col.getFilterValue() as [string, string]) || ["", ""];
                    return (
                      <th key={id}>
                        <div className="d-flex gap-1">
                          <input
                            ref={(el) => {
                              filterRefs.current[id] = el;
                            }}
                            className="form-control form-control-sm"
                            placeholder="min"
                            value={val[0] ?? ""}
                            onChange={(e) => col.setFilterValue([e.target.value, val[1] ?? ""])}
                          />
                          <input
                            className="form-control form-control-sm"
                            placeholder="max"
                            value={val[1] ?? ""}
                            onChange={(e) => col.setFilterValue([val[0] ?? "", e.target.value])}
                          />
                        </div>
                      </th>
                    );
                  }

                  return (
                    <th key={id}>
                      <input
                        ref={(el) => {
                          filterRefs.current[id] = el;
                        }}
                        className="form-control form-control-sm"
                        placeholder="filter…"
                        value={(col.getFilterValue() as string) ?? ""}
                        onChange={(e) => col.setFilterValue(e.target.value)}
                      />
                    </th>
                  );
                })}
              </tr>
            )}
          </thead>

          <tbody>
            {table.getRowModel().rows.map((row) => (
              <tr
                key={row.id}
                style={{
                  background: row.getIsSelected() ? "rgba(47,129,247,0.10)" : undefined,
                }}
              >
                {leafCols.map((col) => {
                  // checkbox cell
                  if (col.id === "__select") {
                    return (
                      <td key={col.id} style={{ textAlign: "center", width: 42 }}>
                        {/* call the column cell renderer */}
                        {typeof col.columnDef.cell === "function"
                          ? col.columnDef.cell({ row } as any)
                          : null}
                      </td>
                    );
                  }

                  const v = row.getValue<any>(col.id);
                  const text = v === null || v === undefined || v === "" ? "—" : String(v);

                  return (
                    <td key={col.id} className="text-nowrap" style={{ textAlign: "left" }}>
                      <span className="d-inline-block w-100 text-start">{text}</span>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      <div className="d-flex flex-wrap gap-2 align-items-center justify-content-between mt-2">
        <div className="d-flex gap-2 align-items-center">
          <button
            className="btn btn-outline-secondary btn-sm"
            onClick={() => table.setPageIndex(0)}
            disabled={!table.getCanPreviousPage()}
            title="First"
          >
            <i className="bi bi-chevron-bar-left" />
          </button>
          <button
            className="btn btn-outline-secondary btn-sm"
            onClick={() => table.previousPage()}
            disabled={!table.getCanPreviousPage()}
            title="Prev"
          >
            <i className="bi bi-chevron-left" />
          </button>

          <span className="small text-secondary">
            Page <b>{table.getState().pagination.pageIndex + 1}</b> of <b>{table.getPageCount()}</b>
          </span>

          <button
            className="btn btn-outline-secondary btn-sm"
            onClick={() => table.nextPage()}
            disabled={!table.getCanNextPage()}
            title="Next"
          >
            <i className="bi bi-chevron-right" />
          </button>
          <button
            className="btn btn-outline-secondary btn-sm"
            onClick={() => table.setPageIndex(table.getPageCount() - 1)}
            disabled={!table.getCanNextPage()}
            title="Last"
          >
            <i className="bi bi-chevron-bar-right" />
          </button>
        </div>

        <div className="d-flex gap-2 align-items-center">
          <span className="small text-secondary">Rows/page</span>
          <select
            className="form-select form-select-sm"
            style={{ width: 120 }}
            value={table.getState().pagination.pageSize}
            onChange={(e) => table.setPageSize(Number(e.target.value))}
          >
            {[10, 20, 50, 100, 200].map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </div>
      </div>
    </div>
  );
}
