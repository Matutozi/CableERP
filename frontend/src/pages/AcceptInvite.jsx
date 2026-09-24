import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import Field from "../components/Field.jsx";
import { useAuth } from "../context/AuthContext.jsx";
import { api } from "../services/api.js";

/**
 * Claiming an invitation. Reachable with no account and no session, by design — the whole point is
 * that the invited person does not have one yet.
 *
 * The token is never shown or explained. If it is expired, spent or invented, the server answers
 * the same way for all three, so this page cannot be used to work out which.
 */
const fieldError = (value) => (Array.isArray(value) ? value.join(" ") : value) || undefined;

export default function AcceptInvite() {
  const { token } = useParams();
  const navigate = useNavigate();
  const { refresh } = useAuth();
  const [fullName, setFullName] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [errors, setErrors] = useState({});
  const [busy, setBusy] = useState(false);

  async function submit(event) {
    event.preventDefault();
    setErrors({});
    setBusy(true);
    try {
      await api.acceptInvitation({ token, username: username.trim(), full_name: fullName.trim(), password });
      // Accepting signs them in, so the app should simply be there.
      await refresh();
      navigate("/", { replace: true });
    } catch (err) {
      // ApiError carries the raw DRF body on `data`; `message` is the first error flattened.
      setErrors({ ...(err.data ?? {}), detail: err.data?.token ? undefined : err.message });
    } finally {
      setBusy(false);
    }
  }

  // The server answers expired, spent and invented links identically, so this page cannot be
  // used to tell them apart.
  const invalidLink = Array.isArray(errors.token) ? errors.token[0] : errors.token;

  return (
    <div className="auth-page">
      <form className="auth-card" onSubmit={submit}>
        <h1>Join your team</h1>
        {invalidLink ? (
          <>
            <div className="alert alert-error">{invalidLink}</div>
            <p className="hint">
              Invitation links work once and expire after a week. Ask whoever invited you to send a new one.
            </p>
            <button type="button" className="btn btn-secondary btn-block" onClick={() => navigate("/login")}>
              Go to sign in
            </button>
          </>
        ) : (
          <>
            <p className="hint">Choose a username and a password. Only you will know the password.</p>
            {errors.detail && <div className="alert alert-error">{errors.detail}</div>}

            <Field label="Your name">
              <input value={fullName} onChange={(e) => setFullName(e.target.value)} autoComplete="name" />
            </Field>
            <Field label="Username" hint={fieldError(errors.username)}>
              <input
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoCapitalize="none"
                autoComplete="username"
                required
              />
            </Field>
            <Field
              label="Password"
              hint={fieldError(errors.password) ?? "At least 8 characters, not all numbers."}
            >
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="new-password"
                required
              />
            </Field>

            <button type="submit" className="btn btn-primary btn-block" disabled={busy}>
              {busy ? "Joining…" : "Join"}
            </button>
          </>
        )}
      </form>
    </div>
  );
}
