import { useEffect, useState } from "react";
import { api, type Row } from "../api";
import DataGrid from "../components/DataGrid";

const ACTIONS: Record<string, string> = {
  "auth.login": "Signed in", "auth.password_changed": "Changed own password", "setup.first_admin": "Set up the system",
  "user.add": "Added a user", "user.edit": "Changed a user", "import.preview": "Uploaded a workbook",
  "import.confirm": "Confirmed an import", "import.discard": "Discarded an import", "import.restore": "Restored an import",
  "aliases.save": "Saved product names", "reports.download": "Downloaded reports",
};

export default function Audit() {
  const [rows, setRows] = useState<Row[]>([]);
  useEffect(() => {
    api<Row[]>("/audit?limit=1000").then((r) => setRows(r.map((x) => ({
      ...x,
      what: ACTIONS[String(x.action)] ?? x.action,
      at: String(x.at).replace(" ", "T"),
      detail: Object.entries((x.details as object) ?? {}).map(([k, v]) => `${k}: ${v}`).join(", "),
    }))));
  }, []);
  return (
    <>
      <h2>Audit log</h2>
      <p className="hint">Every sign-in, import, user change and download, newest first. Times are UTC.</p>
      <DataGrid rows={rows} totals={false} exportName="audit_log" height={600}
        cols={[["at", "When (UTC)"], ["username", "User"], ["what", "What"], ["detail", "Details"]]} />
    </>
  );
}
