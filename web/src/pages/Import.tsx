import { useEffect, useState } from "react";
import { api, download } from "../api";
import DataGrid from "../components/DataGrid";
import { inr, when } from "../format";
import { useData } from "../session";

interface Batch {
  id: number;
  filename: string;
  status: "pending" | "active" | "replaced" | "discarded";
  summary: {
    counts: Record<string, number>;
    current_counts: Record<string, number> | null;
    new_parties: string[];
    new_products: string[];
    totals: { purchase_before_gst: number; sales_before_gst: number };
    checks: { count: number; rows: Record<string, string>[] };
    sheets?: Record<string, string>;
  };
  warnings: string[];
  created_by: string | null;
  created_at: string;
  confirmed_by: string | null;
  confirmed_at: string | null;
}

const SHEETS: [string, string][] = [
  ["purchase", "Purchase bills"], ["sales", "Sales bills"], ["po", "Purchase orders"], ["so", "Sales orders"],
  ["debit_notes", "Debit note lines"], ["credit_notes", "Credit note lines"], ["opening_creditors", "Opening balances (creditors)"],
  ["opening_debtors", "Opening balances (debtors)"],
];

const STATUS: Record<Batch["status"], string> = {
  pending: "Waiting for confirmation", active: "In use now", replaced: "Replaced", discarded: "Discarded",
};

export default function Import() {
  const { reload } = useData();
  const [batches, setBatches] = useState<Batch[]>([]);
  const [preview, setPreview] = useState<Batch | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [done, setDone] = useState("");
  const [inputKey, setInputKey] = useState(0);

  const refresh = () => api<Batch[]>("/imports").then(setBatches).catch((e) => setError(e.message));
  useEffect(() => {
    refresh();
  }, []);

  async function run(label: string, fn: () => Promise<void>) {
    setBusy(label);
    setError("");
    setDone("");
    try {
      await fn();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  }

  const upload = () => run("Reading the workbook…", async () => {
    const form = new FormData();
    form.append("file", file!);
    setPreview(await api<Batch>("/imports", { method: "POST", body: form }));
    setFile(null);
    setInputKey((k) => k + 1);
    refresh();
  });

  const confirm = (b: Batch) => run("Saving…", async () => {
    await api(`/imports/${b.id}/confirm`, { method: "POST" });
    setPreview(null);
    setDone(`${b.filename} is now the data behind every report.`);
    refresh();
    reload();
  });

  const discard = (b: Batch) => run("Discarding…", async () => {
    await api(`/imports/${b.id}/discard`, { method: "POST" });
    setPreview(null);
    refresh();
  });

  const restore = (b: Batch) => {
    if (!window.confirm(`Bring back ${b.filename}? It replaces the data in use now (which can be restored the same way).`)) return;
    run("Restoring…", async () => {
      await api(`/imports/${b.id}/restore`, { method: "POST" });
      setDone(`${b.filename} is back in use.`);
      refresh();
      reload();
    });
  };

  const pending = preview ?? batches.find((b) => b.status === "pending") ?? null;

  return (
    <>
      <p className="hint">Upload the Master Sheet workbook (.xlsx), or a workbook with just the data sheets (Purchase,
        Sales, PO, SO and, if you use them, Debit Notes / Credit Notes; other sheet names such as “Purchase Register”
        are recognised too). You see what was found before anything is saved. Confirming makes it the data behind
        every report and replaces the previous import, which stays listed below and can be brought back. The
        complete Master Sheet, with the Total Debtor Creditor, masters and Display sheets and all formulas, is then
        made for you: use <b>Download Master Sheet</b> at the top of the reports.</p>

      <div className="card upload">
        <input key={inputKey} type="file" accept=".xlsx,.xlsm" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        <button className="primary" disabled={!file || !!busy} onClick={upload}>Upload and check</button>
        {busy && <span className="muted"><span className="spinner" /> {busy}</span>}
      </div>
      {error && <div className="error">{error}</div>}
      {done && <div className="notice good">{done}</div>}

      {pending && (
        <div className="card">
          <div className="card-head">
            <h3>Check before saving: {pending.filename}</h3>
          </div>
          <table className="plain">
            <thead>
              <tr><th>Sheet</th><th className="num">In this file</th>{pending.summary.current_counts && <th className="num">In use now</th>}</tr>
            </thead>
            <tbody>
              {SHEETS.map(([k, label]) => (
                <tr key={k}>
                  <td>{label}</td>
                  <td className="num">{inr(pending.summary.counts[k])}</td>
                  {pending.summary.current_counts && <td className="num">{inr(pending.summary.current_counts[k])}</td>}
                </tr>
              ))}
            </tbody>
          </table>
          {pending.summary.sheets && (
            <p className="muted">Sheets used: {Object.entries(pending.summary.sheets)
              .map(([kind, sheet]) => (kind === sheet ? kind : `${kind} (from “${sheet}”)`)).join(", ")}</p>
          )}
          <p>Purchases before GST: <b>₹{inr(pending.summary.totals.purchase_before_gst)}</b> · Sales before GST: <b>₹{inr(pending.summary.totals.sales_before_gst)}</b></p>
          {pending.summary.current_counts && (
            <>
              <p><b>New parties</b> ({pending.summary.new_parties.length}): {pending.summary.new_parties.join(", ") || "none"}</p>
              <p><b>New products</b> ({pending.summary.new_products.length}): {pending.summary.new_products.join(", ") || "none"}</p>
            </>
          )}
          {pending.warnings.length > 0 && (
            <div className="notice warn"><b>Warnings</b><ul>{pending.warnings.map((w) => <li key={w}>{w}</li>)}</ul></div>
          )}
          {pending.summary.checks.count > 0 && (
            <details>
              <summary>{pending.summary.checks.count} row(s) to look at (missing date, quantity or amount)</summary>
              <DataGrid rows={pending.summary.checks.rows} height="auto" totals={false} search={false}
                cols={[["sheet", "Sheet"], ["row", "Row"], ["party", "Party"], ["issue", "What to check"]]} />
            </details>
          )}
          <div className="actions">
            <button className="primary" disabled={!!busy} onClick={() => confirm(pending)}>
              {pending.summary.current_counts ? "Confirm and replace the data in use" : "Confirm and save"}
            </button>
            <button className="secondary" disabled={!!busy} onClick={() => discard(pending)}>Discard</button>
          </div>
        </div>
      )}

      <h3>Import history</h3>
      <table className="plain wide">
        <thead>
          <tr><th>File</th><th>Status</th><th>Uploaded</th><th>Confirmed</th><th className="num">Purchase / sales bills</th><th /></tr>
        </thead>
        <tbody>
          {batches.map((b) => (
            <tr key={b.id}>
              <td>{b.filename}</td>
              <td><span className={`badge ${b.status}`}>{STATUS[b.status]}</span></td>
              <td>{when(b.created_at)} <span className="muted">by {b.created_by}</span></td>
              <td>{b.confirmed_at ? <>{when(b.confirmed_at)} <span className="muted">by {b.confirmed_by}</span></> : ""}</td>
              <td className="num">{b.summary.counts.purchase} / {b.summary.counts.sales}</td>
              <td className="row-actions">
                {b.status !== "discarded" && (
                  <button className="link" onClick={() => download(`/imports/${b.id}/file`, b.filename)}>Download file</button>
                )}
                {b.status === "replaced" && <button className="link" disabled={!!busy} onClick={() => restore(b)}>Restore</button>}
              </td>
            </tr>
          ))}
          {!batches.length && <tr><td colSpan={6} className="muted">Nothing imported yet</td></tr>}
        </tbody>
      </table>
    </>
  );
}
