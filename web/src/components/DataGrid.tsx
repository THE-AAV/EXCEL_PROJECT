import { AllCommunityModule, ModuleRegistry, themeQuartz, type ColDef, type GridApi } from "ag-grid-community";
import { AgGridReact } from "ag-grid-react";
import { useMemo, useRef, useState } from "react";
import type { Row } from "../api";
import { day, inr, pct, rate } from "../format";

ModuleRegistry.registerModules([AllCommunityModule]);

const theme = themeQuartz.withParams({
  fontFamily: "inherit",
  fontSize: 13,
  headerFontWeight: 600,
  accentColor: "#1f4e79",
  rowHeight: 34,
  headerHeight: 38,
});

export type Kind = "text" | "money" | "qty" | "num" | "rate" | "pct" | "date" | "int";

/** [field, header, kind]; money / qty / num columns get a total in the pinned bottom row. */
export type Col = [string, string, Kind?];

const FORMAT: Record<Kind, (v: unknown) => string> = {
  text: (v) => (v == null ? "" : String(v)),
  money: inr,
  qty: inr,
  num: rate,
  int: inr,
  rate,
  pct,
  date: day,
};

interface Props {
  rows: Row[];
  cols: Col[];
  height?: number | "auto";
  totals?: boolean;
  search?: boolean;
  exportName?: string;
  onRowClick?: (row: Row) => void;
  emptyText?: string;
  /** many columns: fixed widths with sideways scrolling instead of squeezing them to fit */
  wide?: boolean;
  /** fields kept in view on the left while scrolling sideways */
  pin?: string[];
}

export default function DataGrid({ rows, cols, height = 480, totals = true, search = true, exportName,
  onRowClick, emptyText = "Nothing to show", wide = false, pin = [] }: Props) {
  const apiRef = useRef<GridApi | null>(null);
  const [text, setText] = useState("");
  const [shown, setShown] = useState<Row[]>(rows);

  // rows left after search / column filters, for the count and the totals row
  // (collected on data and filter changes only: the totals row itself would otherwise retrigger it)
  const collect = (api: GridApi) => {
    const out: Row[] = [];
    api.forEachNodeAfterFilter((n) => n.data && out.push(n.data));
    setShown(out);
  };

  const columnDefs = useMemo<ColDef[]>(() => cols.map(([field, headerName, kind = "text"]) => {
    const numeric = kind !== "text" && kind !== "date";
    return {
      field,
      headerName,
      valueFormatter: (p) => FORMAT[kind](p.value),
      type: numeric ? "rightAligned" : undefined,
      filter: numeric ? "agNumberColumnFilter" : kind === "date" ? "agDateColumnFilter" : "agTextColumnFilter",
      filterParams: kind === "date" ? { comparator: dateCompare } : undefined,
      comparator: kind === "date" ? (a: string, b: string) => (a ?? "").localeCompare(b ?? "") : undefined,
      minWidth: kind === "text" ? 140 : 110,
      flex: wide ? undefined : kind === "text" ? 1.4 : 1,
      width: wide ? (kind === "text" ? 170 : 130) : undefined,
      pinned: pin.includes(field) ? "left" : undefined,
      tooltipValueGetter: kind === "text" ? (p) => (p.value == null ? "" : String(p.value)) : undefined,
    } as ColDef;
  }), [cols, wide, pin.join("|")]); // eslint-disable-line react-hooks/exhaustive-deps

  const pinned = useMemo(() => {
    if (!totals || !shown.length) return undefined;
    const sums: Row = {};
    let any = false;
    cols.forEach(([field, , kind], i) => {
      if (kind === "money" || kind === "qty" || kind === "num") {
        sums[field] = shown.reduce((s, r) => s + (typeof r[field] === "number" ? (r[field] as number) : 0), 0);
        any = true;
      } else if (i === 0) sums[field] = "Total";
    });
    return any ? [sums] : undefined;
  }, [totals, shown, cols]);

  const auto = height === "auto" || rows.length <= 12;
  return (
    <div className="grid-wrap">
      {(search || exportName) && (
        <div className="grid-tools">
          {search && (
            <input className="search" placeholder="Search…" value={text}
              onChange={(e) => {
                setText(e.target.value);
                apiRef.current?.setGridOption("quickFilterText", e.target.value);
              }} />
          )}
          <span className="muted">{shown.length} of {rows.length} rows</span>
          {exportName && (
            <button className="link" onClick={() => apiRef.current?.exportDataAsCsv({ fileName: `${exportName}.csv` })}>
              Download CSV
            </button>
          )}
        </div>
      )}
      <div style={auto ? undefined : { height }}>
        <AgGridReact
          theme={theme}
          rowData={rows}
          columnDefs={columnDefs}
          pinnedBottomRowData={pinned}
          domLayout={auto ? "autoHeight" : "normal"}
          defaultColDef={{ sortable: true, resizable: true, filter: true, wrapHeaderText: true, autoHeaderHeight: true }}
          overlayNoRowsTemplate={`<span class="muted">${emptyText}</span>`}
          onGridReady={(e) => {
            apiRef.current = e.api;
          }}
          onFirstDataRendered={(e) => collect(e.api)}
          onRowDataUpdated={(e) => collect(e.api)}
          onFilterChanged={(e) => collect(e.api)}
          onRowClicked={(e) => e.data && !e.rowPinned && onRowClick?.(e.data)}
          rowClass={onRowClick ? "clickable" : undefined}
          tooltipShowDelay={400}
        />
      </div>
    </div>
  );
}

function dateCompare(filter: Date, cell: string | null) {
  if (!cell) return -1;
  const d = new Date(`${cell.slice(0, 10)}T00:00:00`);
  return d < filter ? -1 : d > filter ? 1 : 0;
}
