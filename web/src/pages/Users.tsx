import { useEffect, useState, type FormEvent } from "react";
import { api, type Role, type User } from "../api";
import { when } from "../format";
import { useAuth } from "../session";

const ROLE_HELP: Record<Role, string> = {
  admin: "Everything: users, imports, product names, audit log",
  editor: "Enters transactions and sees all reports",
  viewer: "Read-only: reports, dashboard and downloads",
};

export default function Users() {
  const { user: me } = useAuth();
  const [users, setUsers] = useState<User[]>([]);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [form, setForm] = useState({ username: "", full_name: "", role: "viewer" as Role, password: "" });

  const [office, setOffice] = useState<{ urls: string[]; live_file: string; data_dir: string } | null>(null);
  useEffect(() => { api<typeof office>("/office").then(setOffice).catch(() => undefined); }, []);

  const refresh = () => api<User[]>("/users").then(setUsers).catch((e) => setError(e.message));
  useEffect(() => {
    refresh();
  }, []);

  async function act(fn: () => Promise<unknown>, done: string) {
    setError("");
    setMsg("");
    try {
      await fn();
      setMsg(done);
      refresh();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  const add = (e: FormEvent) => {
    e.preventDefault();
    act(async () => {
      await api("/users", { method: "POST", json: form });
      setForm({ username: "", full_name: "", role: "viewer", password: "" });
    }, `Added ${form.username}. Give them their user ID and password.`);
  };

  const patch = (u: User, body: object, done: string) => act(() => api(`/users/${u.id}`, { method: "PATCH", json: body }), done);

  return (
    <>
      {office && (
        <div className="card">
          <h3>Share the app with your office</h3>
          <p className="hint">Add each person below, then give them their user ID, password and this address to open
            in their browser (on the same office network or Wi-Fi):</p>
          <ul className="urls">{office.urls.map((u) => <li key={u}><code>{u}</code></li>)}</ul>
          <p className="hint">The Master Sheet with every entry is kept up to date on the computer running the app:
            <br /><code>{office.live_file}</code><br />The data is in <code>{office.data_dir}</code>; when the app is started with Start_Web_App.bat a copy is saved every day in its <code>backups</code> folder.</p>
        </div>
      )}
      <h2>Users and roles</h2>
      <div className="role-help">
        {(Object.keys(ROLE_HELP) as Role[]).map((r) => <div key={r}><span className={`badge role-${r}`}>{r}</span> {ROLE_HELP[r]}</div>)}
      </div>
      {error && <div className="error">{error}</div>}
      {msg && <div className="notice good">{msg}</div>}
      <table className="plain wide">
        <thead><tr><th>User ID</th><th>Name</th><th>Role</th><th>Status</th><th>Last sign-in</th><th /></tr></thead>
        <tbody>
          {users.map((u) => (
            <tr key={u.id} className={u.active ? "" : "inactive"}>
              <td>{u.username}{u.id === me?.id && <span className="muted"> (you)</span>}</td>
              <td>{u.full_name}</td>
              <td>
                <select value={u.role} onChange={(e) => patch(u, { role: e.target.value }, `${u.username} is now ${e.target.value}`)}>
                  <option value="admin">admin</option><option value="editor">editor</option><option value="viewer">viewer</option>
                </select>
              </td>
              <td>{u.active ? (u.locked ? "Locked (wrong passwords)" : "Active") : "Switched off"}</td>
              <td>{when(u.last_login)}</td>
              <td className="row-actions">
                {u.locked && <button className="link" onClick={() => patch(u, { unlock: true }, `${u.username} unlocked`)}>Unlock</button>}
                <button className="link" onClick={() => {
                  const p = window.prompt(`New password for ${u.username} (at least 8 characters)`);
                  if (p) patch(u, { password: p }, `Password reset for ${u.username}`);
                }}>Reset password</button>
                <button className="link" onClick={() => patch(u, { active: !u.active },
                  u.active ? `${u.username} switched off` : `${u.username} switched on`)}>
                  {u.active ? "Switch off" : "Switch on"}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <form className="card form-grid" onSubmit={add}>
        <h3>Add a user</h3>
        <div><label className="field-label">User ID</label>
          <input value={form.username} required pattern="[A-Za-z0-9._@\-]+" title="Letters, numbers, . _ @ -"
            onChange={(e) => setForm({ ...form, username: e.target.value })} /></div>
        <div><label className="field-label">Name</label>
          <input value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} /></div>
        <div><label className="field-label">Role</label>
          <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value as Role })}>
            <option value="viewer">viewer (read-only)</option><option value="editor">editor</option><option value="admin">admin</option>
          </select></div>
        <div><label className="field-label">First password</label>
          <input type="text" autoComplete="off" value={form.password} minLength={8} required
            onChange={(e) => setForm({ ...form, password: e.target.value })} /></div>
        <div className="actions"><button className="primary">Add user</button></div>
      </form>
    </>
  );
}
