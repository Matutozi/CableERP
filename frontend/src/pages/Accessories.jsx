import { useEffect, useMemo, useRef, useState } from "react";
import CatalogueHeader from "../components/CatalogueHeader.jsx";
import CostNote from "../components/CostNote.jsx";
import Field from "../components/Field.jsx";
import Icon from "../components/Icon.jsx";
import InlinePrice from "../components/InlinePrice.jsx";
import MoneyInput from "../components/MoneyInput.jsx";
import TrendPanel from "../components/TrendPanel.jsx";
import { api } from "../services/api.js";
import { ACCESSORY_UNITS, toNumber, unitLabel } from "../services/format.js";

/** Stays open after each add so a batch of accessories can be entered in one go. */
function AccessoryForm({ onAdded, onClose }) {
  const [name, setName] = useState("");
  const [unit, setUnit] = useState("piece");
  const [price, setPrice] = useState("");
  const [lastAdded, setLastAdded] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const nameRef = useRef(null);

  async function handleSubmit(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const created = await api.createAccessory({ name, unit, default_price: toNumber(price).toFixed(2) });
      onAdded(created);
      setLastAdded(created.name);
      setName("");
      setPrice("");
      nameRef.current?.focus();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel">
      <h2 className="panel-title">Add accessories</h2>
      {error && <div className="alert alert-error">{error}</div>}
      {lastAdded && !error && <p className="added-note">Added {lastAdded}. Add another, or tap Done.</p>}
      <form onSubmit={handleSubmit}>
        <div className="field-grid">
          <Field label="Name">
            <input ref={nameRef} value={name} onChange={(event) => setName(event.target.value)}
              placeholder="e.g. 13A switched socket" required autoFocus />
          </Field>
          <Field label="Sold per">
            <select value={unit} onChange={(event) => setUnit(event.target.value)}>
              {ACCESSORY_UNITS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
          </Field>
          <Field label="Price">
            <MoneyInput value={price} onChange={setPrice} placeholder="₦0.00" required />
          </Field>
        </div>
        <div className="form-actions">
          <button type="button" className="btn btn-secondary" onClick={onClose}>Done</button>
          <button type="submit" className="btn btn-primary" disabled={busy}>{busy ? "Adding…" : "Add accessory"}</button>
        </div>
      </form>
    </section>
  );
}

function AccessoryRow({ accessory, onSave, onDelete }) {
  const [name, setName] = useState(accessory.name);
  const [showTrend, setShowTrend] = useState(false);

  useEffect(() => setName(accessory.name), [accessory.name]);

  async function commitName() {
    const trimmed = name.trim();
    if (!trimmed || trimmed === accessory.name) {
      setName(accessory.name);
      return;
    }
    try {
      await onSave({ name: trimmed });
    } catch {
      setName(accessory.name);
    }
  }

  return (
    <div className="acc-row">
      <input className="inline-name" value={name} aria-label={`Name of ${accessory.name}`}
        onChange={(event) => setName(event.target.value)} onBlur={commitName}
        onKeyDown={(event) => event.key === "Enter" && event.currentTarget.blur()} />
      <select className="inline-select" value={accessory.unit} aria-label={`Unit for ${accessory.name}`}
        onChange={(event) => onSave({ unit: event.target.value }).catch(() => {})}>
        {ACCESSORY_UNITS.map(([value, label]) => <option key={value} value={value}>per {label.toLowerCase()}</option>)}
      </select>
      <InlinePrice price={accessory.default_price} label={`Price for ${accessory.name}`} onSave={(price) => onSave({ default_price: price })} />
      <button type="button" className="icon-btn icon-btn-danger" aria-label={`Delete ${accessory.name}`} onClick={onDelete}>
        <Icon name="trash" size={14} />
      </button>
      <button type="button" className="cost-toggle" aria-expanded={showTrend}
        title="Show how this price and its cost have moved" onClick={() => setShowTrend(!showTrend)}>
        <CostNote row={accessory} unit={unitLabel(accessory.unit, 1)} />
      </button>
      {showTrend && <TrendPanel kind="accessory" id={accessory.id} unit={accessory.unit} />}
    </div>
  );
}

export default function Accessories() {
  const [accessories, setAccessories] = useState(null);
  const [error, setError] = useState("");
  const [adding, setAdding] = useState(false);
  const [search, setSearch] = useState("");

  useEffect(() => {
    api.listAccessories().then(setAccessories).catch((err) => setError(err.message));
  }, []);

  const visible = useMemo(() => {
    const term = search.trim().toLowerCase();
    return term ? accessories?.filter((accessory) => accessory.name.toLowerCase().includes(term)) : accessories;
  }, [accessories, search]);

  async function save(accessory, patch) {
    setError("");
    try {
      const updated = await api.updateAccessory(accessory.id, {
        name: accessory.name,
        unit: accessory.unit,
        default_price: accessory.default_price,
        order: accessory.order,
        ...patch,
      });
      setAccessories((current) => current.map((entry) => (entry.id === updated.id ? updated : entry)));
    } catch (err) {
      setError(err.message);
      throw err;
    }
  }

  async function remove(accessory) {
    if (!window.confirm(`Delete ${accessory.name}? Existing quotes are not affected.`)) return;
    try {
      await api.deleteAccessory(accessory.id);
      setAccessories((current) => current.filter((entry) => entry.id !== accessory.id));
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <div className="page">
      <CatalogueHeader
        action={!adding && <button type="button" className="btn btn-secondary" onClick={() => setAdding(true)}>Add accessory</button>} />

      {error && <div className="alert alert-error">{error}</div>}

      {adding && (
        <AccessoryForm onClose={() => setAdding(false)}
          onAdded={(created) => setAccessories((current) => [...(current ?? []), created])} />
      )}

      {accessories?.length > 0 && (
        <input className="search" type="search" placeholder="Search accessories" value={search}
          onChange={(event) => setSearch(event.target.value)} aria-label="Search accessories" />
      )}

      {visible === null ? (
        !error && <p className="muted">Loading…</p>
      ) : accessories.length === 0 ? (
        !adding && (
          <div className="empty">
            No accessories yet. Add the other things you sell, such as sockets, switches, breakers, conduit and tape.
          </div>
        )
      ) : visible.length === 0 ? (
        <div className="empty">No accessories match your search.</div>
      ) : (
        <div className="panel flush acc-rows">
          {visible.map((accessory) => (
            <AccessoryRow key={accessory.id} accessory={accessory}
              onSave={(patch) => save(accessory, patch)} onDelete={() => remove(accessory)} />
          ))}
        </div>
      )}
    </div>
  );
}
