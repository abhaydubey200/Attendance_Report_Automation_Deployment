import { useState, type FormEvent } from "react";
import { ApiError } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { BrandMark } from "../components/Brand";
import { Notice } from "../components/ui";

/** Shown only when the server runs with auth.mode "local". */
export function LoginPage() {
  const { login, notice } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(username, password);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to reach the server.");
    } finally {
      setPassword("");
      setBusy(false);
    }
  }

  return (
    <div className="splash">
      <form className="splash-card" onSubmit={onSubmit} aria-label="Sign in">
        <BrandMark size="lg" />
        <h1>Daily Attendance</h1>
        <p className="muted">APIS India Limited · Sign in to continue</p>
        {notice && <Notice>{notice}</Notice>}
        {error && <Notice kind="fail">{error}</Notice>}
        <label htmlFor="username">Username</label>
        <input id="username" autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} required />
        <label htmlFor="password">Password</label>
        <input id="password" type="password" autoComplete="current-password" value={password}
          onChange={(e) => setPassword(e.target.value)} required />
        <button type="submit" className="btn btn-primary" disabled={busy}>
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </div>
  );
}

export function UnavailablePage({ message }: { message: string }) {
  return (
    <div className="splash">
      <div className="splash-card">
        <BrandMark size="lg" />
        <h1>Daily Attendance</h1>
        <Notice kind="fail">{message}</Notice>
        <button type="button" className="btn btn-primary" onClick={() => window.location.reload()}>
          Try again
        </button>
      </div>
    </div>
  );
}
