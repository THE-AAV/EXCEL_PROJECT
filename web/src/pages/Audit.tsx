import { useEffect, useState } from "react";
import { api, type Row } from "../api";
import DataGrid from "../components/DataGrid";
import { when } from "../format";

const ACTIONS: Record<string, string> = {
  "auth.login": "Signed in", "auth.password_changed": "Changed own password", "setup.first_admin": "Set up the system",
  "user.add": "Added a user", "user.edit": "Changed a user", "import.preview": "Uploaded a workbook",
  "import.confirm": "Confirmed an import", "import.discard": "Discarded an import", "import.restore": "Restored an import",
  "aliases.save": "Saved product names", "reports.download": "Downloaded reports",
  "master_sheet.download": "Downloaded the Master Sheet", "entry.order": "Entered an order",
  "entry.invoice": "Entered an invoice", "entry.note": "Entered a debit / credit note", "entry.expenses": "Changed expenses",
  "entry.settlement": "Entered a payment / receipt", "entry.undo": "Undid an entry",
};

const HIDE = new Set(["batch"]);

export default function Audit() {
  const [rows, setRows] = useState<Row[]>([]);
  useEffect(() => {
    api<Row[]>("/audit?limit=1000").then((r) => setRows(r.map((x) => ({
      ...x,
      what: ACTIONS[String(x.action)] ?? x.action,
      at: when(String(x.at).replace(" ", "T")),
      detail: Object.entries((x.details as Record<string, unknown>) ?? {}).filter(([k, v]) => !HIDE.has(k) && v !== "")
        .map(([k, v]) => (k === "entry" || k === "details" ? String(v) : `${k}: ${v}`)).join(" · "),
    }))));
  }, []);
  return (
    <>
      <h2>Audit log</h2>
      <p className="hint">Who did what and when, newest first: every entry (with its details), undo, import, sign-in,
        user change and download. Search for a name, a party or a bill number.</p>
      <DataGrid rows={rows} totals={false} exportName="audit_log" height={600}
        cols={[["at", "When"], ["username", "User"], ["what", "What"], ["detail", "Details"]]} />
    </>
  );
}
