import { useState } from "react";
import { Link } from "react-router-dom";
import Field from "../components/Field.jsx";
import { useAuth } from "../context/AuthContext.jsx";

export default function Register() {
  const { register } = useAuth();
  const [form, setForm] = useState({ business_name: "", full_name: "", username: "", email: "", password: "" });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const setField = (name) => (event) => setForm({ ...form, [name]: event.target.value });

  async function handleSubmit(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await register(form);
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  }

  return (
    <div className="auth-page">
      <form className="auth-card" onSubmit={handleSubmit}>
        <div className="auth-brand"><span className="brand-mark" />CableERP</div>
        <h1>Create your account</h1>
        <p className="auth-lead">Add your address, bank details and logo after signing up.</p>
        {error && <div className="alert alert-error">{error}</div>}
        <Field label="Business name">
          <input value={form.business_name} onChange={setField("business_name")} placeholder="e.g. Acme-Oaks Ventures Limited" required />
        </Field>
        <Field label="Your name" hint="Used as “Prepared by” on your quotes.">
          <input autoComplete="name" value={form.full_name} onChange={setField("full_name")} />
        </Field>
        <Field label="Username">
          <input autoComplete="username" autoCapitalize="none" value={form.username} onChange={setField("username")} required />
        </Field>
        <Field label="Email (optional)">
          <input type="email" autoComplete="email" value={form.email} onChange={setField("email")} />
        </Field>
        <Field label="Password" hint="At least 8 characters, not all numbers.">
          <input type="password" autoComplete="new-password" value={form.password} onChange={setField("password")} required />
        </Field>
        <button type="submit" className="btn btn-primary btn-block" disabled={busy}>{busy ? "Creating account…" : "Create account"}</button>
        <p className="auth-switch">Already have an account? <Link to="/login">Sign in</Link></p>
      </form>
    </div>
  );
}
