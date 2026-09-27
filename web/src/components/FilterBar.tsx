import { useState } from "react";
import { download } from "../api";
import { useData } from "../session";
import MultiSelect from "./MultiSelect";

export default function FilterBar() {
  const { filters, setFilters, status, filterQuery, loading } = useData();
  const [busy, setBusy] = useState(false);
  const o = status?.options;
  const set = (patch: Partial<typeof filters>) => setFilters({ ...filters, ...patch });

  return (
    <div className="filter-bar">
      <div>
        <label className="field-label" title="Balances and ageing are worked out as on this date">Balances as on</label>
        <input type="date" value={filters.as_of} onChange={(e) => e.target.value && set({ as_of: e.target.value })} />
      </div>
      <div>
        <label className="field-label" title="P&L period, by bill date">P&L from</label>
        <input type="date" value={filters.date_from} min={o?.min_date ?? undefined}
          onChange={(e) => set({ date_from: e.target.value })} />
      </div>
      <div>
        <label className="field-label">to</label>
        <input type="date" value={filters.date_to} max={o?.max_date ?? undefined}
          onChange={(e) => set({ date_to: e.target.value })} />
      </div>
      {o && (
        <>
          <MultiSelect label="Products" options={o.products} value={filters.products} onChange={(v) => set({ products: v })} />
          <MultiSelect label="Type" options={o.types} value={filters.types} onChange={(v) => set({ types: v })} />
          <MultiSelect label="Sub type" options={o.sub_types} value={filters.sub_types} onChange={(v) => set({ sub_types: v })} />
          <MultiSelect label="Company" options={o.companies} value={filters.companies} onChange={(v) => set({ companies: v })} />
        </>
      )}
      <div className="filter-actions">
        {loading && <span className="spinner" title="Working out the reports" />}
        <button className="secondary" disabled={busy}
          onClick={async () => {
            setBusy(true);
            try {
              await download(`/reports/excel${filterQuery}`, "Business_Reports.xlsx");
            } finally {
              setBusy(false);
            }
          }}>
          {busy ? "Preparing…" : "Download all reports (Excel)"}
        </button>
      </div>
    </div>
  );
}
