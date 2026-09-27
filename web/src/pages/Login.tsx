import { useEffect, useState, type FormEvent } from "react";
import { api, type User } from "../api";
import { useAuth } from "../session";

export default function Login() {
  const { setUser } = useAuth();
  const [setup, setSetup] = useState<boolean | null>(null);
  const [username, setUsername] = useState("");
  const [fullName, setFullName] = useState("");
  const [password, setPassword] = useState("");
  const [repeat, setRepeat] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api<{ needs_first_admin: boolean }>("/setup").then((r) => setSetup(r.needs_first_admin)).catch(() => setSetup(false));
  }, []);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError("");
    if (setup && password !== repeat) return setError("The two passwords are different");
    setBusy(true);
    try {
      const user = setup
        ? await api<User>("/setup", { method: "POST", json: { username, full_name: fullName, role: "admin", password } })
        : await api<User>("/auth/login", { method: "POST", json: { username, password } });
      setUser(user);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (setup === null) return null;
  return (
    <div className="login-page">
      <form className="login-card" onSubmit={submit}>
        <div className="brand big">
          <span className="logo" /> Business Reports
        </div>
        {setup ? (
          <p className="muted">First-time setup: create the admin account. The admin adds everyone else.</p>
        ) : (
          <p className="muted">Sign in with your user ID and password.</p>
        )}
        <label className="field-label">User ID</label>
        <input autoFocus autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} required />
        {setup && (
          <>
            <label className="field-label">Your name</label>
            <input value={fullName} onChange={(e) => setFullName(e.target.value)} />
          </>
        )}
        <label className="field-label">Password</label>
        <input type="password" autoComplete={setup ? "new-password" : "current-password"} value={password}
          onChange={(e) => setPassword(e.target.value)} required minLength={setup ? 8 : undefined} />
        {setup && (
          <>
            <label className="field-label">Repeat password</label>
            <input type="password" autoComplete="new-password" value={repeat} onChange={(e) => setRepeat(e.target.value)} required />
            <p className="hint">At least 8 characters.</p>
          </>
        )}
        {error && <div className="error">{error}</div>}
        <button className="primary" disabled={busy}>{busy ? "Please wait…" : setup ? "Create admin and sign in" : "Sign in"}</button>
      </form>
    </div>
  );
}
