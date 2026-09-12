import { useEffect, useState } from "react";
import Field from "../components/Field.jsx";
import { useAuth } from "../context/AuthContext.jsx";
import { api } from "../services/api.js";
import { formatDateTime } from "../services/format.js";

const FIELDS = [
  "business_name",
  "address",
  "phone_numbers",
  "email",
  "bank_name",
  "account_name",
  "account_number",
  "disclaimer",
  "payment_terms",
  "quote_validity",
  "vat_rate",
];
// Changing these asks for the password again, because they decide where customers send money.
const BANK_FIELDS = ["bank_name", "account_name", "account_number"];

export default function Settings() {
  const { refresh, signOutEverywhere } = useAuth();
  const [form, setForm] = useState(null);
  const [saved, setSaved] = useState(null);
  const [password, setPassword] = useState("");
  const [logo, setLogo] = useState(null);
  const [activity, setActivity] = useState(null);
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  function applyProfile(profile) {
    const fields = Object.fromEntries(FIELDS.map((name) => [name, profile[name] ?? ""]));
    setForm(fields);
    setSaved(fields);
    setLogo(profile.logo);
  }

  const bankChanged = Boolean(form && saved && BANK_FIELDS.some((name) => form[name] !== saved[name]));

  const loadActivity = () => api.listActivity().then(setActivity).catch(() => setActivity([]));

  useEffect(() => {
    api.getProfile().then(applyProfile).catch((err) => setError(err.message));
    loadActivity();
  }, []);

  async function run(action, task, successMessage) {
    setBusy(action);
    setError("");
    setNotice("");
    try {
      await task();
      setNotice(successMessage);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy("");
      window.scrollTo({ top: 0, behavior: "smooth" });
    }
  }

  function handleSubmit(event) {
    event.preventDefault();
    run("save", async () => {
      applyProfile(await api.updateProfile(bankChanged ? { ...form, current_password: password } : form));
      setPassword("");
      await refresh(); // the business name is shown in the sidebar
      loadActivity();
    }, "Settings saved.");
  }

  function uploadLogo(file) {
    if (file) run("logo", async () => setLogo((await api.uploadLogo(file)).logo), "Logo updated.");
  }

  const removeLogo = () => run("logo", async () => setLogo((await api.removeLogo()).logo), "Logo removed.");

  if (!form) {
    return <div className="page">{error ? <div className="alert alert-error">{error}</div> : <p className="muted">Loading…</p>}</div>;
  }

  const setField = (name) => (event) => setForm({ ...form, [name]: event.target.value });

  return (
    <form className="page settings" onSubmit={handleSubmit}>
      <div className="page-head">
        <div>
          <h1>Business settings</h1>
          <div className="page-sub">Shown on every quote you generate.</div>
        </div>
      </div>

      {error && <div className="alert alert-error">{error}</div>}
      {notice && <div className="alert alert-success">{notice}</div>}

      <section className="panel">
        <h2 className="panel-title">Business</h2>
        <div className="field-grid wide-cols">
          <Field label="Business name">
            <input value={form.business_name} onChange={setField("business_name")} required />
          </Field>
          <Field label="Phone" hint="Separate numbers with commas.">
            <input type="tel" value={form.phone_numbers} onChange={setField("phone_numbers")} placeholder="08179452969, 08033857090" />
          </Field>
          <Field label="Address" wide>
            <textarea rows={2} value={form.address} onChange={setField("address")} />
          </Field>
          <Field label={<>Email <span className="optional">(optional)</span></>}>
            <input type="email" value={form.email} onChange={setField("email")} />
          </Field>
          <Field label="VAT rate (%)" hint="Set to 0 if you don't charge VAT.">
            <input inputMode="decimal" value={form.vat_rate} onChange={setField("vat_rate")} />
          </Field>
        </div>

        <div className="logo-field">
          <span className="field-label">Logo</span>
          <label className={dragging ? "dropzone dragging" : "dropzone"}
            onDragOver={(event) => {
              event.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(event) => {
              event.preventDefault();
              setDragging(false);
              uploadLogo(event.dataTransfer.files[0]);
            }}>
            <input type="file" accept="image/*" hidden disabled={!!busy}
              onChange={(event) => {
                uploadLogo(event.target.files[0]);
                event.target.value = "";
              }} />
            <span className="dropzone-thumb">{logo && <img src={logo} alt="Business logo" />}</span>
            <span>
              <span className="dropzone-title">
                {busy === "logo" ? "Uploading…" : logo ? "Tap to replace, or drop a file" : "Tap to upload, or drop a file"}
              </span>
              <span className="dropzone-hint">PNG or JPG, up to 2 MB. Shown at the top of your quotes.</span>
            </span>
          </label>
          {logo && (
            <button type="button" className="btn-link btn-link-danger" onClick={removeLogo} disabled={!!busy}>Remove logo</button>
          )}
        </div>
      </section>

      <section className="panel">
        <h2 className="panel-title">Bank details</h2>
        <div className="field-grid">
          <Field label="Bank">
            <input value={form.bank_name} onChange={setField("bank_name")} placeholder="e.g. Wema Bank" />
          </Field>
          <Field label="Account number">
            <input inputMode="numeric" value={form.account_number} onChange={setField("account_number")} />
          </Field>
          <Field label="Account name">
            <input value={form.account_name} onChange={setField("account_name")} />
          </Field>
        </div>
        {bankChanged && (
          <div className="confirm-bank">
            <Field label="Confirm your password" hint="Bank details decide where your customers send money, so we check it's you.">
              <input type="password" autoComplete="current-password" value={password} required
                onChange={(event) => setPassword(event.target.value)} />
            </Field>
          </div>
        )}
      </section>

      <section className="panel">
        <h2 className="panel-title">Quote terms</h2>
        <div className="field-grid wide-cols">
          <Field label="Payment terms">
            <input value={form.payment_terms} onChange={setField("payment_terms")} placeholder="e.g. 100% down payment" />
          </Field>
          <Field label="Quotation validity">
            <input value={form.quote_validity} onChange={setField("quote_validity")} placeholder="e.g. 24 hours from the date of this quotation" />
          </Field>
          <Field label="Disclaimer" wide>
            <textarea rows={3} value={form.disclaimer} onChange={setField("disclaimer")} />
          </Field>
        </div>
      </section>

      <section className="panel">
        <h2 className="panel-title">Recent activity</h2>
        {activity === null ? (
          <p className="muted small">Loading…</p>
        ) : activity.length === 0 ? (
          <p className="muted small">Nothing recorded yet. Price changes, bank changes and quotes will appear here.</p>
        ) : (
          <ul className="activity">
            {activity.map((entry) => (
              <li key={entry.id}>
                <span className="activity-what">
                  <b>{entry.action_label}</b>{entry.reference ? ` · ${entry.reference}` : ""}
                  <span className="activity-detail">{entry.summary}</span>
                </span>
                <span className="activity-meta">{formatDateTime(entry.created_at)} · {entry.user_name}</span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="panel">
        <h2 className="panel-title">Security</h2>
        <p className="muted small">
          Signs you out on every phone and computer, including this one. Use it if a staff phone is lost or a shared
          computer stayed signed in.
        </p>
        <button type="button" className="btn btn-secondary mt-8" disabled={!!busy}
          onClick={() => {
            if (window.confirm("Sign out of all devices? You'll need to sign in again here too.")) signOutEverywhere();
          }}>
          Sign out of all devices
        </button>
      </section>

      <div>
        <button type="submit" className="btn btn-primary" disabled={!!busy}>{busy === "save" ? "Saving…" : "Save changes"}</button>
      </div>
    </form>
  );
}
