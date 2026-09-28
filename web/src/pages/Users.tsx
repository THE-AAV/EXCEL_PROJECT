import { useEffect, useState, type FormEvent } from "react";
import { api, type Role, type User } from "../api";
import { when } from "../format";
import { useAuth } from "../session";

const ROLE_HELP: Record<Role, string> = {
  admin: "Everything: users, imports, product names, audit log",
  editor: "Enters transactions and sees all reports",
  viewer: "Read-only: reports, dashboard, files and downloads",
};

export default function Users() {
  const { user: me } = useAuth();
  const [users, setUsers] = useState<User[]>([]);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const blank = { username: "", full_name: "", role: "viewer" as Role, password: "", can_files: false };
  const [form, setForm] = useState(blank);

  const [office, setOffice] = useState<{ urls: string[]; live_file: string; data_dir: string; online: boolean;
    public_url: string; internet_url: string; internet_problem: string } | null>(null);
  useEffect(() => {
    // the internet link takes a few seconds to appear after the app starts, and changes if it has to reconnect
    const load = () => api<typeof office>("/office").then(setOffice).catch(() => undefined);
    load();
    const t = window.setInterval(load, 10_000);
    return () => window.clearInterval(t);
  }, []);

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
      setForm(blank);
    }, `Added ${form.username}. Give them their user ID and password.`);
  };

  const patch = (u: User, body: object, done: string) => act(() => api(`/users/${u.id}`, { method: "PATCH", json: body }), done);

  return (
    <>
      {office && (office.online ? (
        <div className="card">
          <h3>Share the app</h3>
          <p className="hint">Add each person below, then give them their user ID, password and this address. It works
            from any computer or phone with internet:</p>
          <ul className="urls"><li><code>{office.public_url}</code></li></ul>
        </div>
      ) : (
        <div className="card">
          <h3>Share the app with your office</h3>
          <p className="hint">Add each person below, then give them their user ID, password and this address to open
            in their browser (on the same office network or Wi-Fi):</p>
          <ul className="urls">{office.urls.map((u) => <li key={u}><code>{u}</code></li>)}</ul>
          <p className="hint">From anywhere else (home, phone data, another city) they open this internet link:</p>
          {office.internet_url
            ? <ul className="urls"><li><code>{office.internet_url}</code></li></ul>
            : <p className="hint">{office.internet_problem ? `No internet link right now: ${office.internet_problem}.`
                : "The internet link appears here a few seconds after the app starts (with Start Business Reports)."}</p>}
          {office.internet_url && <p className="hint">This link changes each time the app is started, so share the new
            one after a restart. The app only works while this computer is on and the app window is open.</p>}
          <p className="hint">The Master Sheet with every entry is kept up to date on the computer running the app:
            <br /><code>{office.live_file}</code><br />The data is in <code>{office.data_dir}</code>; when the app is started with Start_Web_App.bat a copy is saved every day in its <code>backups</code> folder.</p>
        </div>
      ))}
      <h2>Users and roles</h2>
      <div className="role-help">
        {(Object.keys(ROLE_HELP) as Role[]).map((r) => <div key={r}><span className={`badge role-${r}`}>{r}</span> {ROLE_HELP[r]}</div>)}
      </div>
      {error && <div className="error">{error}</div>}
      {msg && <div className="notice good">{msg}</div>}
      <table className="plain wide">
        <thead><tr><th>User ID</th><th>Name</th><th>Role</th><th title="Upload, rename, move and delete in Files (admins always can)">Files</th><th>Status</th><th>Last sign-in</th><th /></tr></thead>
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
              <td>
                <label className="check" title="Upload, rename, move and delete in Files">
                  <input type="checkbox" checked={u.role === "admin" || !!u.can_files} disabled={u.role === "admin"}
                    onChange={(e) => patch(u, { can_files: e.target.checked },
                      e.target.checked ? `${u.username} can now upload and delete files` : `${u.username} can now only look at files`)} />
                  {" "}can change</label>
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
        <div><label className="check"><input type="checkbox" checked={form.can_files || form.role === "admin"}
          disabled={form.role === "admin"} onChange={(e) => setForm({ ...form, can_files: e.target.checked })} />
          {" "}Can upload and delete files</label></div>
        <div className="actions"><button className="primary">Add user</button></div>
      </form>
    </>
  );
}
