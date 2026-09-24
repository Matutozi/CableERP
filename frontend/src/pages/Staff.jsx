import { useEffect, useState } from "react";
import Field from "../components/Field.jsx";
import Icon from "../components/Icon.jsx";
import { api } from "../services/api.js";
import { formatDate } from "../services/format.js";

/**
 * The permission checkboxes.
 *
 * `features` comes from the server, never a list kept here. A hard-coded copy drifts the moment a
 * permission is added, and the consequence is worse than a missing tick box: this picker submits
 * exactly what it knows about, so an unknown permission would be stripped from whoever is being
 * edited, silently.
 */
function PermissionPicker({ features, value, onChange }) {
  const toggle = (feature) =>
    onChange(value.includes(feature) ? value.filter((f) => f !== feature) : [...value, feature]);

  return (
    <div className="permission-grid">
      {features.map(({ value: feature, label }) => (
        <label key={feature} className="permission-option">
          <input type="checkbox" checked={value.includes(feature)} onChange={() => toggle(feature)} />
          <span>{label}</span>
        </label>
      ))}
    </div>
  );
}

function StorePicker({ stores, allStores, selected, onChange }) {
  return (
    <>
      <label className="permission-option">
        <input
          type="checkbox"
          checked={allStores}
          onChange={(event) => onChange({ all_stores: event.target.checked, stores: [] })}
        />
        <span>
          Every branch
          <small>Including any opened later.</small>
        </span>
      </label>
      {!allStores && (
        <div className="permission-grid">
          {stores.map((store) => (
            <label key={store.id} className="permission-option">
              <input
                type="checkbox"
                checked={selected.includes(store.id)}
                onChange={() =>
                  onChange({
                    all_stores: false,
                    stores: selected.includes(store.id)
                      ? selected.filter((id) => id !== store.id)
                      : [...selected, store.id],
                  })
                }
              />
              <span>{store.name}</span>
            </label>
          ))}
          {stores.length === 0 && <p className="list-empty">No branches yet.</p>}
        </div>
      )}
    </>
  );
}

function InviteForm({ features, roles, stores, onInvited, onClose }) {
  const [contact, setContact] = useState("");
  const [fullName, setFullName] = useState("");
  const [roleId, setRoleId] = useState(roles[0]?.id ?? "");
  const [permissions, setPermissions] = useState(roles[0]?.permissions ?? []);
  const [scope, setScope] = useState({ all_stores: false, stores: [] });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  // Choosing a role fills the tick boxes; the owner can then tune them for this one person. The
  // copy is the point — editing the template later must not change what this person may do.
  function chooseRole(id) {
    setRoleId(id);
    const role = roles.find((r) => String(r.id) === String(id));
    if (role) setPermissions(role.permissions);
  }

  async function submit(event) {
    event.preventDefault();
    setError("");
    setBusy(true);
    try {
      const looksLikeEmail = contact.includes("@");
      const created = await api.createInvitation({
        email: looksLikeEmail ? contact.trim() : "",
        phone: looksLikeEmail ? "" : contact.trim(),
        full_name: fullName.trim(),
        role_template: roleId,
        permissions,
        all_stores: scope.all_stores,
        stores: scope.stores,
      });
      onInvited(created);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="panel invite-form" onSubmit={submit}>
      <h3>Invite someone</h3>
      {error && <div className="alert alert-error">{error}</div>}

      <div className="field-grid">
        <Field label="Phone or email" hint="Where you will send the link.">
          <input
            value={contact}
            onChange={(e) => setContact(e.target.value)}
            placeholder="08030000000"
            required
          />
        </Field>
        <Field label="Their name">
          <input value={fullName} onChange={(e) => setFullName(e.target.value)} placeholder="Emeka Obi" />
        </Field>
        <Field label="Role">
          <select value={roleId} onChange={(e) => chooseRole(e.target.value)}>
            {roles.map((role) => (
              <option key={role.id} value={role.id}>
                {role.name}
              </option>
            ))}
          </select>
        </Field>
      </div>

      <fieldset className="access-block">
        <legend>What they can do</legend>
        <PermissionPicker features={features} value={permissions} onChange={setPermissions} />
      </fieldset>

      <fieldset className="access-block">
        <legend>Which branches they can see</legend>
        <StorePicker
          stores={stores}
          allStores={scope.all_stores}
          selected={scope.stores}
          onChange={setScope}
        />
      </fieldset>

      <div className="form-actions">
        <button type="button" className="btn btn-ghost" onClick={onClose}>
          Cancel
        </button>
        <button type="submit" className="btn btn-primary" disabled={busy}>
          {busy ? "Creating…" : "Create invite link"}
        </button>
      </div>
    </form>
  );
}

function InviteLink({ invitation, onDone }) {
  const [copied, setCopied] = useState(false);
  const url = `${window.location.origin}${invitation.invite_url}`;

  async function copy() {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
    } catch {
      // Clipboard access is refused in some mobile browsers; the field is selectable regardless.
      setCopied(false);
    }
  }

  return (
    <div className="panel invite-link">
      <h3>Send this link to {invitation.full_name || invitation.email || invitation.phone}</h3>
      <p className="hint">
        It works once and expires in a week. <strong>Copy it now</strong> — for your security it is not
        stored, so it cannot be shown again. If you lose it, invite them again.
      </p>
      <input className="invite-url" readOnly value={url} onFocus={(e) => e.target.select()} />
      <div className="form-actions">
        <button type="button" className="btn btn-secondary" onClick={copy}>
          {copied ? "Copied" : "Copy link"}
        </button>
        <a
          className="btn btn-primary"
          href={`https://wa.me/?text=${encodeURIComponent(url)}`}
          target="_blank"
          rel="noreferrer"
        >
          Send on WhatsApp
        </a>
        <button type="button" className="btn btn-ghost" onClick={onDone}>
          Done
        </button>
      </div>
    </div>
  );
}

function MemberRow({ member, features, stores, onSaved, onError }) {
  const [open, setOpen] = useState(false);
  const [permissions, setPermissions] = useState(member.permissions);
  const [scope, setScope] = useState({ all_stores: member.all_stores, stores: member.stores });
  const [busy, setBusy] = useState(false);

  async function save(extra = {}) {
    setBusy(true);
    try {
      const updated = await api.updateMember(member.id, {
        permissions,
        all_stores: scope.all_stores,
        stores: scope.stores,
        ...extra,
      });
      onSaved(updated);
      setOpen(false);
    } catch (err) {
      onError(err.message);
    } finally {
      setBusy(false);
    }
  }

  const suspended = member.status === "suspended";

  return (
    <div className="member">
      <button type="button" className="member-head" aria-expanded={open} onClick={() => setOpen(!open)}>
        <span className="member-main">
          <span className="member-name">
            {member.full_name}
            {member.is_owner && <span className="tag">Owner</span>}
            {suspended && <span className="tag tag-muted">Suspended</span>}
          </span>
          <span className="member-sub">
            {member.role_label || "Member"} · {member.store_names.join(", ") || "No branch"} · joined{" "}
            {formatDate(member.created_at)}
          </span>
        </span>
        <Icon name={open ? "chevron-up" : "chevron-down"} size={16} />
      </button>

      {open && (
        <div className="member-body">
          <fieldset className="access-block">
            <legend>What they can do</legend>
            <PermissionPicker features={features} value={permissions} onChange={setPermissions} />
          </fieldset>
          <fieldset className="access-block">
            <legend>Which branches they can see</legend>
            <StorePicker
              stores={stores}
              allStores={scope.all_stores}
              selected={scope.stores}
              onChange={setScope}
            />
          </fieldset>
          <div className="form-actions">
            <button
              type="button"
              className="btn btn-ghost"
              disabled={busy}
              onClick={() => save({ status: suspended ? "active" : "suspended" })}
            >
              {suspended ? "Reinstate" : "Suspend"}
            </button>
            <button type="button" className="btn btn-primary" disabled={busy} onClick={() => save()}>
              {busy ? "Saving…" : "Save access"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

/** Who works here, what each may do, and how to add someone. */
export default function Staff() {
  const [members, setMembers] = useState(null);
  const [invitations, setInvitations] = useState([]);
  const [roles, setRoles] = useState([]);
  const [stores, setStores] = useState([]);
  const [features, setFeatures] = useState([]);
  const [inviting, setInviting] = useState(false);
  const [newInvite, setNewInvite] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([
      api.listStaff(),
      api.listInvitations(),
      api.listRoles(),
      api.listStores(),
      api.listFeatures(),
    ])
      .then(([staff, invites, roleList, storeList, featureList]) => {
        setMembers(staff);
        setInvitations(invites);
        setRoles(roleList);
        setStores(storeList);
        setFeatures(featureList);
      })
      .catch((err) => setError(err.message));
  }, []);

  async function cancel(invitation) {
    if (!window.confirm(`Cancel the invite for ${invitation.email || invitation.phone}?`)) return;
    try {
      await api.cancelInvitation(invitation.id);
      setInvitations((current) => current.filter((i) => i.id !== invitation.id));
    } catch (err) {
      setError(err.message);
    }
  }

  if (error && members === null) return <div className="page alert alert-error">{error}</div>;
  if (members === null) return <div className="page">Loading…</div>;

  const pending = invitations.filter((i) => i.status === "pending");

  return (
    <div className="page">
      <div className="page-head">
        <h1>Staff</h1>
        {!inviting && !newInvite && (
          <button type="button" className="btn btn-primary" onClick={() => setInviting(true)}>
            Invite someone
          </button>
        )}
      </div>

      {error && <div className="alert alert-error">{error}</div>}

      {newInvite && (
        <InviteLink
          invitation={newInvite}
          onDone={() => {
            setInvitations((current) => [newInvite, ...current]);
            setNewInvite(null);
          }}
        />
      )}

      {inviting && (
        <InviteForm
          features={features}
          roles={roles}
          stores={stores}
          onClose={() => setInviting(false)}
          onInvited={(created) => {
            setInviting(false);
            setNewInvite(created);
          }}
        />
      )}

      {pending.length > 0 && (
        <section className="panel">
          <h2 className="panel-title">Waiting to join</h2>
          {pending.map((invitation) => (
            <div key={invitation.id} className="list-row">
              <span>
                {invitation.full_name || invitation.email || invitation.phone}
                <span className="doc-small"> · {invitation.role_label}</span>
              </span>
              <button type="button" className="btn btn-ghost" onClick={() => cancel(invitation)}>
                Cancel
              </button>
            </div>
          ))}
        </section>
      )}

      <section className="panel flush">
        {members.map((member) => (
          <MemberRow
            key={member.id}
            member={member}
            features={features}
            stores={stores}
            onError={setError}
            onSaved={(updated) =>
              setMembers((current) => current.map((m) => (m.id === updated.id ? updated : m)))
            }
          />
        ))}
      </section>
    </div>
  );
}
