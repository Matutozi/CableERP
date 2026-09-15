import { Fragment, useEffect, useRef, useState } from "react";
import CatalogueHeader from "../components/CatalogueHeader.jsx";
import CostNote from "../components/CostNote.jsx";
import Field from "../components/Field.jsx";
import Icon from "../components/Icon.jsx";
import InlinePrice from "../components/InlinePrice.jsx";
import MoneyInput from "../components/MoneyInput.jsx";
import TrendPanel from "../components/TrendPanel.jsx";
import { api } from "../services/api.js";
import { CABLE_UNITS, formatNaira, toNumber, unitLabel } from "../services/format.js";

function CableTypeForm({ initial, submitLabel, onSubmit, onCancel }) {
  const [name, setName] = useState(initial?.name ?? "");
  const [unit, setUnit] = useState(initial?.unit ?? "coil");
  const [hasColours, setHasColours] = useState(initial?.has_colour_variants ?? false);
  const [colours, setColours] = useState((initial?.colour_options ?? []).join(", "));
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function handleSubmit(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await onSubmit({
        name,
        unit,
        has_colour_variants: hasColours,
        colour_options: colours.split(",").map((colour) => colour.trim()).filter(Boolean),
      });
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  }

  return (
    <form onSubmit={handleSubmit}>
      {error && <div className="alert alert-error">{error}</div>}
      <div className="field-grid">
        <Field label="Name">
          <input value={name} onChange={(event) => setName(event.target.value)} placeholder="e.g. Singles" required autoFocus />
        </Field>
        <Field label="Sold per">
          <select value={unit} onChange={(event) => setUnit(event.target.value)}>
            {CABLE_UNITS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </Field>
        <Field label="Colours" as="div" wide>
          <label className="check">
            <input type="checkbox" checked={hasColours} onChange={(event) => setHasColours(event.target.checked)} />
            Sold in different colours
          </label>
          {hasColours && (
            <input className="mt-8" value={colours} onChange={(event) => setColours(event.target.value)}
              placeholder="Red, Black, Yellow/Green" aria-label="Colour options, separated by commas" />
          )}
          {hasColours && <span className="field-hint">Separate colours with commas.</span>}
        </Field>
      </div>
      <div className="form-actions">
        <button type="button" className="btn btn-secondary" onClick={onCancel}>Cancel</button>
        <button type="submit" className="btn btn-primary" disabled={busy}>{busy ? "Saving…" : submitLabel}</button>
      </div>
    </form>
  );
}

function AddSizeForm({ cableType, onAdded, onClose }) {
  const [label, setLabel] = useState("");
  const [price, setPrice] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const labelRef = useRef(null);

  async function handleSubmit(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      onAdded(await api.createSize(cableType.id, { size_label: label, default_price: toNumber(price).toFixed(2) }));
      setLabel("");
      setPrice("");
      labelRef.current?.focus();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="inline-form" onSubmit={handleSubmit}>
      <input ref={labelRef} value={label} onChange={(event) => setLabel(event.target.value)} placeholder="Size, e.g. 2.5mm x 3C"
        aria-label="New size" required autoFocus />
      <MoneyInput value={price} onChange={setPrice} placeholder="Price" aria-label="New size price" required />
      <div className="inline-form-actions">
        <button type="submit" className="btn btn-primary" disabled={busy}>{busy ? "Adding…" : "Add"}</button>
        <button type="button" className="btn btn-secondary" onClick={onClose}>Done</button>
      </div>
      {error && <div className="alert alert-error inline-form-error">{error}</div>}
    </form>
  );
}

function CableTypeCard({ cableType, open, onToggle, onChange, onDelete }) {
  const [editing, setEditing] = useState(false);
  const [addingSize, setAddingSize] = useState(false);
  const [trendFor, setTrendFor] = useState(null);
  const [error, setError] = useState("");

  const updateSizes = (update) => onChange((current) => ({ ...current, sizes: update(current.sizes) }));

  async function savePrice(size, price) {
    setError("");
    try {
      const updated = await api.updateSize(size.id, { size_label: size.size_label, default_price: price, order: size.order });
      updateSizes((sizes) => sizes.map((entry) => (entry.id === updated.id ? updated : entry)));
    } catch (err) {
      setError(err.message);
      throw err;
    }
  }

  async function deleteSize(size) {
    if (!window.confirm(`Delete ${size.size_label} ${cableType.name}? Existing quotes are not affected.`)) return;
    try {
      await api.deleteSize(size.id);
      updateSizes((sizes) => sizes.filter((entry) => entry.id !== size.id));
    } catch (err) {
      setError(err.message);
    }
  }

  if (editing) {
    return (
      <section className="panel">
        <h2 className="panel-title">Edit {cableType.name}</h2>
        <CableTypeForm initial={cableType} submitLabel="Save changes" onCancel={() => setEditing(false)}
          onSubmit={async (data) => {
            const updated = await api.updateCableType(cableType.id, { ...data, order: cableType.order });
            onChange(() => updated);
            setEditing(false);
          }} />
      </section>
    );
  }

  const prices = cableType.sizes.map((size) => toNumber(size.default_price));
  const summary = [
    `${cableType.sizes.length} ${cableType.sizes.length === 1 ? "size" : "sizes"}`,
    prices.length ? `₦${formatNaira(Math.min(...prices))}–₦${formatNaira(Math.max(...prices))}` : null,
    `per ${unitLabel(cableType.unit, 1)}`,
  ].filter(Boolean).join(", ");

  return (
    <div className="acc">
      <button type="button" className="acc-head" onClick={onToggle} aria-expanded={open}>
        <span className="acc-title">
          <span className="acc-name">{cableType.name}</span>
          <span className="acc-sub">{summary}</span>
        </span>
        {cableType.has_colour_variants && <span className="badge badge-neutral">Colour variants</span>}
        <span className={open ? "chevron open" : "chevron"}><Icon name="chevron" size={14} strokeWidth={1.6} /></span>
      </button>

      {open && (
        <div className="acc-body">
          {error && <div className="alert alert-error">{error}</div>}
          {cableType.has_colour_variants && (
            <div className="chips">{cableType.colour_options.map((colour) => <span key={colour} className="chip">{colour}</span>)}</div>
          )}
          {cableType.sizes.map((size) => (
            <Fragment key={size.id}>
              <div className="list-row">
                <button type="button" className="list-row-name cost-toggle" aria-expanded={trendFor === size.id}
                  title="Show how this price and its cost have moved"
                  onClick={() => setTrendFor(trendFor === size.id ? null : size.id)}>
                  <span className="cost-toggle-name">{size.size_label}</span>
                  <CostNote row={size} unit={unitLabel(cableType.unit, 1)} />
                </button>
                <span className="list-row-actions">
                  <InlinePrice price={size.default_price} label={`Price for ${size.size_label}`} onSave={(price) => savePrice(size, price)} />
                  <button type="button" className="icon-btn icon-btn-danger" aria-label={`Delete ${size.size_label}`} onClick={() => deleteSize(size)}>
                    <Icon name="trash" size={14} />
                  </button>
                </span>
              </div>
              {trendFor === size.id && <TrendPanel kind="size" id={size.id} unit={cableType.unit} />}
            </Fragment>
          ))}
          {cableType.sizes.length === 0 && !addingSize && <p className="list-empty">No sizes yet.</p>}
          {addingSize ? (
            <AddSizeForm cableType={cableType} onClose={() => setAddingSize(false)}
              onAdded={(size) => updateSizes((sizes) => [...sizes, size])} />
          ) : (
            <button type="button" className="btn-link" onClick={() => setAddingSize(true)}>
              <Icon name="plus" size={14} strokeWidth={1.7} />Add size
            </button>
          )}
          <div className="acc-foot">
            <button type="button" className="btn-link btn-link-muted" onClick={() => setEditing(true)}>Edit type</button>
            <button type="button" className="btn-link btn-link-danger" onClick={onDelete}>Delete type</button>
          </div>
        </div>
      )}
    </div>
  );
}

export default function Catalogue() {
  const [types, setTypes] = useState(null);
  const [error, setError] = useState("");
  const [adding, setAdding] = useState(false);
  const [openId, setOpenId] = useState(null);

  useEffect(() => {
    api.listCableTypes()
      .then((list) => {
        setTypes(list);
        setOpenId(list[0]?.id ?? null);
      })
      .catch((err) => setError(err.message));
  }, []);

  const changeType = (id) => (update) => setTypes((current) => current.map((type) => (type.id === id ? update(type) : type)));

  async function createType(data) {
    const created = await api.createCableType(data);
    setTypes((current) => [...current, created]);
    setOpenId(created.id);
    setAdding(false);
  }

  async function deleteType(cableType) {
    if (!window.confirm(`Delete ${cableType.name} and all its sizes? Existing quotes are not affected.`)) return;
    try {
      await api.deleteCableType(cableType.id);
      setTypes((current) => current.filter((type) => type.id !== cableType.id));
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <div className="page">
      <CatalogueHeader
        action={!adding && <button type="button" className="btn btn-secondary" onClick={() => setAdding(true)}>Add type</button>} />

      {error && <div className="alert alert-error">{error}</div>}

      {adding && (
        <section className="panel">
          <h2 className="panel-title">New cable type</h2>
          <CableTypeForm submitLabel="Add cable type" onSubmit={createType} onCancel={() => setAdding(false)} />
        </section>
      )}

      {types === null ? (
        !error && <p className="muted">Loading…</p>
      ) : types.length === 0 && !adding ? (
        <div className="empty">No cable types yet. Add one such as “Singles” or “Flex” to get started.</div>
      ) : (
        <div className="acc-list">
          {types.map((cableType) => (
            <CableTypeCard key={cableType.id} cableType={cableType} open={openId === cableType.id}
              onToggle={() => setOpenId(openId === cableType.id ? null : cableType.id)}
              onChange={changeType(cableType.id)} onDelete={() => deleteType(cableType)} />
          ))}
        </div>
      )}
    </div>
  );
}
