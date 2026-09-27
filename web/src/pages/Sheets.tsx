import { useEffect, useState } from "react";
import { api, download, type Row } from "../api";
import DataGrid, { type Col } from "../components/DataGrid";
import { useData } from "../session";

interface Sheet { key: string; name: string; cols: Col[]; rows: Row[] }

export default function Sheets() {
  const { version } = useData();
  const [sheets, setSheets] = useState<Sheet[] | null>(null);
  const [tab, setTab] = useState(() => sessionStorage.getItem("sheet-tab") || "purchase");
  const [error, setError] = useState("");

  useEffect(() => {
    api<Sheet[]>("/sheets").then(setSheets).catch((e) => setError(e.message));
  }, [version]);

  if (error) return <div className="error">{error}</div>;
  if (!sheets) return <span className="spinner" />;
  const sheet = sheets.find((s) => s.key === tab) ?? sheets[0];
  return (
    <>
      <p className="hint">Every entry in the data, sheet by sheet, with the Master Sheet's own column names. Search, filter
        (the ≡ on a column heading) and sort (click a heading); totals are for the rows shown. It refreshes by itself when
        anyone saves an entry.</p>
      <div className="tabs">
        {sheets.map((s) => (
          <button key={s.key} className={s.key === sheet.key ? "active" : ""}
            onClick={() => { setTab(s.key); sessionStorage.setItem("sheet-tab", s.key); }}>
            {s.name} <span className="muted">({s.rows.length})</span>
          </button>
        ))}
        <button className="link push" onClick={() => download("/master-sheet", "Master Sheet.xlsx")}>Download Master Sheet</button>
      </div>
      {sheet.rows.length === 0 ? <p className="muted">No entries in this sheet yet.</p> :
        <DataGrid key={sheet.key} rows={sheet.rows} cols={sheet.cols} height={560} exportName={sheet.name} wide
          pin={sheet.cols.filter(([, h]) => /^party name$/i.test(h)).map(([f]) => f)} />}
    </>
  );
}
