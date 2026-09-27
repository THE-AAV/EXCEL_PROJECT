import { useState, type FormEvent } from "react";
import { api } from "../api";
import { useAuth } from "../session";

export default function Account() {
  const { user } = useAuth();
  const [f, setF] = useState({ current: "", next: "", repeat: "" });
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");

  async function submit(e: FormEvent) {
    e.preventDefault();
    setMsg("");
    setError("");
    if (f.next !== f.repeat) return setError("The two new passwords are different");
    try {
      await api("/auth/password", { method: "POST", json: { current_password: f.current, new_password: f.next } });
      setF({ current: "", next: "", repeat: "" });
      setMsg("Password changed. You have been signed out on other devices.");
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <>
      <h2>My account</h2>
      <p>{user?.full_name || user?.username} · user ID <b>{user?.username}</b> · role <span className={`badge role-${user?.role}`}>{user?.role}</span></p>
      <form className="card narrow" onSubmit={submit}>
        <h3>Change password</h3>
        <label className="field-label">Current password</label>
        <input type="password" autoComplete="current-password" value={f.current} required onChange={(e) => setF({ ...f, current: e.target.value })} />
        <label className="field-label">New password</label>
        <input type="password" autoComplete="new-password" value={f.next} minLength={8} required onChange={(e) => setF({ ...f, next: e.target.value })} />
        <label className="field-label">Repeat new password</label>
        <input type="password" autoComplete="new-password" value={f.repeat} required onChange={(e) => setF({ ...f, repeat: e.target.value })} />
        {error && <div className="error">{error}</div>}
        {msg && <div className="notice good">{msg}</div>}
        <button className="primary">Change password</button>
      </form>
    </>
  );
}
