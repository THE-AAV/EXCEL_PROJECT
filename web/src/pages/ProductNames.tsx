import { useEffect, useState } from "react";
import { api } from "../api";
import { can, useAuth, useData } from "../session";

interface Alias { name_in_sheet: string; report_as: string }

export default function ProductNames() {
  const { user } = useAuth();
  const { reload } = useData();
  const admin = can(user, "admin");
  const [rows, setRows] = useState<Alias[]>([]);
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    api<Alias[]>("/aliases").then(setRows);
  }, []);

  const set = (i: number, patch: Partial<Alias>) => setRows(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));

  async function save() {
    setMsg("");
    setError("");
    try {
      setRows(await api<Alias[]>("/aliases", { method: "PUT", json: rows }));
      setMsg("Saved. The reports now use these names.");
      reload();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <>
      <h2>Product names</h2>
      <p className="hint">When the same product is typed differently (e.g. <i>SOYA BEANS</i> and <i>Soyabean</i>), add a
        row so the reports count them as one. Capital letters and extra spaces are already ignored.</p>
      <table className="plain">
        <thead><tr><th>Name in sheet</th><th>Report as</th>{admin && <th />}</tr></thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              <td>{admin ? <input value={r.name_in_sheet} onChange={(e) => set(i, { name_in_sheet: e.target.value })} /> : r.name_in_sheet}</td>
              <td>{admin ? <input value={r.report_as} onChange={(e) => set(i, { report_as: e.target.value })} /> : r.report_as}</td>
              {admin && <td><button className="link" onClick={() => setRows(rows.filter((_, j) => j !== i))}>Remove</button></td>}
            </tr>
          ))}
          {!rows.length && <tr><td colSpan={3} className="muted">No mappings yet</td></tr>}
        </tbody>
      </table>
      {admin && (
        <div className="actions">
          <button className="secondary" onClick={() => setRows([...rows, { name_in_sheet: "", report_as: "" }])}>Add a row</button>
          <button className="primary" onClick={save}>Save</button>
        </div>
      )}
      {error && <div className="error">{error}</div>}
      {msg && <div className="notice good">{msg}</div>}
    </>
  );
}
