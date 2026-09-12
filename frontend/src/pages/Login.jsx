import { useState } from "react";
import { Link } from "react-router-dom";
import Field from "../components/Field.jsx";
import { useAuth } from "../context/AuthContext.jsx";

export default function Login() {
  const { login } = useAuth();
  const [form, setForm] = useState({ username: "", password: "", remember: false });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const setField = (name) => (event) => setForm({ ...form, [name]: event.target.value });

  async function handleSubmit(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await login(form);
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  }

  return (
    <div className="auth-page">
      <form className="auth-card" onSubmit={handleSubmit}>
        <div className="auth-brand"><span className="brand-mark" />CableERP</div>
        <h1>Sign in</h1>
        <p className="auth-lead">Quotes for your cable business, in one place.</p>
        {error && <div className="alert alert-error">{error}</div>}
        <Field label="Username">
          <input autoComplete="username" autoCapitalize="none" value={form.username} onChange={setField("username")} required />
        </Field>
        <Field label="Password">
          <input type="password" autoComplete="current-password" value={form.password} onChange={setField("password")} required />
        </Field>
        <label className="check">
          <input type="checkbox" checked={form.remember}
            onChange={(event) => setForm({ ...form, remember: event.target.checked })} />
          Keep me signed in
        </label>
        <button type="submit" className="btn btn-primary btn-block" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
        <p className="auth-switch">New here? <Link to="/register">Create an account</Link></p>
      </form>
    </div>
  );
}
