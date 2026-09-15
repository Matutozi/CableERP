import { useEffect, useMemo, useState } from "react";
import CatalogueHeader from "../components/CatalogueHeader.jsx";
import Combobox from "../components/Combobox.jsx";
import Field from "../components/Field.jsx";
import Icon from "../components/Icon.jsx";
import MoneyInput from "../components/MoneyInput.jsx";
import { api } from "../services/api.js";
import { ALL_UNITS, formatDate, formatNaira, isFractionalUnit, todayIso, toNumber, unitLabel } from "../services/format.js";

let nextKey = 1;

const blankLine = () => ({
  key: nextKey++,
  label: "",
  cable_size: null,
  accessory: null,
  saleUnit: "",
  quantity: "",
  entry_unit: "",
  units_per_entry: "1",
  unit_cost: "",
});

/** Everything the seller can buy, flattened to one pickable list of catalogue rows. */
function buildOptions(cableTypes, accessories) {
  const options = [];
  for (const type of cableTypes) {
    for (const size of type.sizes) {
      options.push({
        value: `${size.size_label} ${type.name}`.trim(),
        hint: `sold per ${unitLabel(type.unit, 1)}`,
        row: { ...size, saleUnit: type.unit, link: { cable_size: size.id, accessory: null } },
      });
    }
  }
  for (const accessory of accessories) {
    options.push({
      value: accessory.name,
      hint: `sold per ${unitLabel(accessory.unit, 1)}`,
      row: { ...accessory, saleUnit: accessory.unit, link: { cable_size: null, accessory: accessory.id } },
    });
  }
  return options;
}

function PurchaseLine({ line, options, onChange, onRemove }) {
  const converts = Boolean(line.saleUnit) && line.entry_unit !== line.saleUnit;
  const perSaleUnit =
    converts && toNumber(line.units_per_entry) > 0 ? toNumber(line.unit_cost) / toNumber(line.units_per_entry) : null;

  function pick(value) {
    const match = options.find((option) => option.value.toLowerCase() === value.trim().toLowerCase());
    if (!match) return onChange({ label: value, cable_size: null, accessory: null, saleUnit: "" });
    const { row } = match;
    onChange({
      label: match.value,
      orphan: false,
      ...row.link,
      saleUnit: row.saleUnit,
      // Default to however this item was bought last time.
      entry_unit: row.purchase_unit || row.saleUnit,
      units_per_entry: row.purchase_unit ? String(toNumber(row.units_per_purchase)) : "1",
    });
  }

  return (
    <div className="item-card purchase-line">
      <div className="item-row">
        <div className="grow">
          <span className="field-label">Item</span>
          <Combobox value={line.label} ariaLabel="Catalogue item" placeholder="Pick from your catalogue"
            options={options} onChange={pick}
            emptyMessage="No match. A delivery has to be recorded against something in your catalogue." />
        </div>
      </div>

      {line.orphan ? (
        <div className="item-error">
          “{line.orphanName}” is no longer in your catalogue, so this line can't be saved as it is.
          Pick the item that replaces it, or remove the line.
        </div>
      ) : !line.saleUnit && line.label.trim() && (
        <div className="item-error">
          Not in your catalogue. Add it under Cables or Accessories first, then record what you paid for it.
        </div>
      )}

      <div className="item-row">
        <label className="w-qty">
          <span className="field-label">Quantity</span>
          <input type="text" inputMode={isFractionalUnit(line.entry_unit) ? "decimal" : "numeric"} placeholder="0"
            value={line.quantity} onChange={(event) => onChange({ quantity: event.target.value.replace(/[^\d.]/g, "") })} />
        </label>
        <label className="unit-select">
          <span className="field-label">Bought by the</span>
          <select value={line.entry_unit} aria-label="Unit bought"
            onChange={(event) => {
              const entry_unit = event.target.value;
              onChange({ entry_unit, units_per_entry: entry_unit === line.saleUnit ? "1" : line.units_per_entry });
            }}>
            {ALL_UNITS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </label>
        <label className="w-price">
          <span className="field-label">Paid per {unitLabel(line.entry_unit, 1) || "unit"}</span>
          <MoneyInput value={line.unit_cost} placeholder="₦0.00" onChange={(value) => onChange({ unit_cost: value })} />
        </label>
      </div>

      {converts && (
        <div className="item-row conversion">
          <label className="w-qty">
            <span className="field-label">{unitLabel(line.saleUnit, 2)} in one {unitLabel(line.entry_unit, 1)}</span>
            <input type="text" inputMode="decimal" value={line.units_per_entry} placeholder="100"
              onChange={(event) => onChange({ units_per_entry: event.target.value.replace(/[^\d.]/g, "") })} />
          </label>
          {perSaleUnit !== null && perSaleUnit > 0 && (
            <span className="field-hint conversion-hint">
              That is ₦{formatNaira(perSaleUnit)} per {unitLabel(line.saleUnit, 1)}, before transport.
            </span>
          )}
        </div>
      )}

      <div className="item-foot">
        <button type="button" className="icon-btn icon-btn-danger" onClick={onRemove} aria-label="Remove line">
          <Icon name="trash" size={15} />
        </button>
        <div className="item-sum">
          <span className="item-total">₦{formatNaira(toNumber(line.quantity) * toNumber(line.unit_cost))}</span>
        </div>
      </div>
    </div>
  );
}

/** A saved delivery turned back into editable lines, matched up with the catalogue again. */
function linesFrom(purchase, options) {
  return purchase.items.map((item) => {
    const match = options.find(
      (option) =>
        (item.cable_size && option.row.link.cable_size === item.cable_size) ||
        (item.accessory && option.row.link.accessory === item.accessory),
    );
    // Its catalogue entry has since been deleted. The line cannot be saved as it stands, so it
    // is flagged rather than quietly dropped — losing part of a recorded delivery on an
    // unrelated edit would be worse than refusing the edit.
    const orphan = !item.cable_size && !item.accessory;
    return {
      key: nextKey++,
      // Left blank for an orphan: the dead name would filter every option out of the picker,
      // making "pick a replacement" impossible to follow. The name is in the message instead.
      label: orphan ? "" : match?.value ?? item.item_name,
      cable_size: item.cable_size,
      accessory: item.accessory,
      orphan,
      orphanName: item.item_name,
      saleUnit: match?.row.saleUnit ?? "",
      quantity: String(toNumber(item.quantity)),
      entry_unit: item.entry_unit,
      units_per_entry: String(toNumber(item.units_per_entry)),
      unit_cost: String(toNumber(item.unit_cost)),
    };
  });
}

function PurchaseForm({ options, purchase, onSaved, onClose }) {
  const [supplier, setSupplier] = useState(purchase?.supplier_name ?? "");
  const [date, setDate] = useState(purchase?.date ?? todayIso());
  const [transport, setTransport] = useState(purchase ? String(toNumber(purchase.additional_cost)) : "");
  const [note, setNote] = useState(purchase?.note ?? "");
  const [lines, setLines] = useState(() => (purchase ? linesFrom(purchase, options) : [blankLine()]));
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const goods = lines.reduce((sum, line) => sum + toNumber(line.quantity) * toNumber(line.unit_cost), 0);
  const total = goods + toNumber(transport);

  const update = (key, patch) => setLines((current) => current.map((line) => (line.key === key ? { ...line, ...patch } : line)));

  async function handleSubmit(event) {
    event.preventDefault();
    setError("");
    const orphans = lines.filter((line) => line.orphan && !line.cable_size && !line.accessory);
    if (orphans.length) {
      return setError(
        `${orphans.map((line) => `“${line.orphanName}”`).join(", ")} is no longer in your catalogue. ` +
          "Pick a replacement for that line or remove it, so this delivery isn't saved without it.",
      );
    }
    const usable = lines.filter((line) => line.cable_size || line.accessory);
    if (!usable.length) return setError("Pick at least one catalogue item this delivery was for.");
    if (usable.some((line) => toNumber(line.quantity) <= 0)) return setError("Enter how many of each item arrived.");
    if (usable.some((line) => line.unit_cost === "")) return setError("Enter what you paid for each item.");

    setBusy(true);
    try {
      const payload = {
        supplier_name: supplier.trim(),
        date,
        additional_cost: toNumber(transport).toFixed(2),
        note: note.trim(),
        items: usable.map((line) => ({
          cable_size: line.cable_size,
          accessory: line.accessory,
          quantity: toNumber(line.quantity).toFixed(2),
          entry_unit: line.entry_unit,
          units_per_entry: toNumber(line.units_per_entry).toFixed(2),
          unit_cost: toNumber(line.unit_cost).toFixed(2),
        })),
      };
      await (purchase ? api.updatePurchase(purchase.id, payload) : api.createPurchase(payload));
      onSaved();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="panel" onSubmit={handleSubmit} noValidate>
      <h2 className="panel-title">{purchase ? "Edit delivery" : "Record a delivery"}</h2>
      {error && <div className="alert alert-error">{error}</div>}

      <div className="field-grid">
        <Field label={<>Supplier <span className="optional">(optional)</span></>}>
          <input value={supplier} onChange={(event) => setSupplier(event.target.value)} placeholder="e.g. Coleman depot" />
        </Field>
        <Field label="Date">
          <input type="date" value={date} onChange={(event) => setDate(event.target.value)} />
        </Field>
        <Field label={<>Transport and clearing <span className="optional">(optional)</span></>}
          hint="Shared across the items by value, so margins aren't flattered.">
          <MoneyInput value={transport} onChange={setTransport} placeholder="₦0.00" />
        </Field>
      </div>

      <div className="section-head">
        <h2>Items</h2>
        <span className="muted small">{lines.length} {lines.length === 1 ? "line" : "lines"}</span>
      </div>

      <div className="item-list">
        {lines.map((line) => (
          <PurchaseLine key={line.key} line={line} options={options}
            onChange={(patch) => update(line.key, patch)}
            onRemove={() => setLines((current) => current.filter((entry) => entry.key !== line.key))} />
        ))}
      </div>

      <div className="add-row">
        <button type="button" className="btn-link" onClick={() => setLines((current) => [...current, blankLine()])}>
          <Icon name="plus" size={15} strokeWidth={1.7} />Add another item
        </button>
      </div>

      <div className="purchase-total">
        <span>Delivery total</span>
        <strong>₦{formatNaira(total)}</strong>
      </div>

      <Field label={<>Note <span className="optional">(optional)</span></>} wide>
        <textarea rows={2} value={note} onChange={(event) => setNote(event.target.value)}
          placeholder="Invoice number, waybill, anything worth remembering." />
      </Field>

      <div className="form-actions">
        <button type="button" className="btn btn-secondary" onClick={onClose}>Cancel</button>
        <button type="submit" className="btn btn-primary" disabled={busy}>
          {busy ? "Saving…" : purchase ? "Save changes" : "Save delivery"}
        </button>
      </div>
    </form>
  );
}

function PurchaseRow({ purchase, onEdit, onDelete }) {
  const [detail, setDetail] = useState(null);
  const [open, setOpen] = useState(false);
  const [error, setError] = useState("");

  async function toggle() {
    setOpen(!open);
    if (open || detail) return;
    try {
      setDetail(await api.getPurchase(purchase.id));
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <div className={open ? "purchase-entry open" : "purchase-entry"}>
      <button type="button" className="purchase-row" aria-expanded={open} onClick={toggle}>
        <span className="purchase-main">
          <span className="purchase-supplier">{purchase.supplier_name || "Supplier not named"}</span>
          <span className="purchase-sub">
            {formatDate(purchase.date)} · {purchase.item_count} {purchase.item_count === 1 ? "item" : "items"}
            {toNumber(purchase.additional_cost) > 0 && ` · ₦${formatNaira(purchase.additional_cost)} transport`}
          </span>
        </span>
        <span className="purchase-amount">₦{formatNaira(purchase.total_cost)}</span>
        <span className={open ? "chevron open" : "chevron"}><Icon name="chevron" size={14} strokeWidth={1.6} /></span>
      </button>

      {open && (
        <div className="purchase-detail">
          {error && <div className="alert alert-error">{error}</div>}
          {!detail && !error ? (
            <p className="muted small">Loading…</p>
          ) : detail && (
            <>
              {detail.items.map((item) => (
                <div key={item.id} className="list-row">
                  <span className="list-row-name">
                    {item.item_name}
                    <span className="cost-note">
                      {Number(item.quantity)} {unitLabel(item.entry_unit, Number(item.quantity))} at
                      {` ₦${formatNaira(item.unit_cost)}`}
                      {item.landed_unit_cost && Number(item.units_per_entry) !== 1 &&
                        ` · ₦${formatNaira(item.landed_unit_cost)} landed per unit sold`}
                    </span>
                  </span>
                  <span className="purchase-amount">₦{formatNaira(item.line_cost)}</span>
                </div>
              ))}
              {toNumber(detail.additional_cost) > 0 && (
                <div className="list-row">
                  <span className="list-row-name">Transport and clearing</span>
                  <span className="purchase-amount">₦{formatNaira(detail.additional_cost)}</span>
                </div>
              )}
              {detail.note && <p className="purchase-note">{detail.note}</p>}
              <div className="acc-foot">
                <button type="button" className="btn-link" onClick={() => onEdit(detail)}>Edit delivery</button>
                <button type="button" className="btn-link btn-link-danger" onClick={onDelete}>Delete delivery</button>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}

export default function Purchases() {
  const [purchases, setPurchases] = useState(null);
  const [count, setCount] = useState(0);
  const [nextPage, setNextPage] = useState(null);
  const [busy, setBusy] = useState(false);
  const [cableTypes, setCableTypes] = useState([]);
  const [accessories, setAccessories] = useState([]);
  const [recording, setRecording] = useState(false);
  const [editing, setEditing] = useState(null);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  const load = () =>
    Promise.all([api.listPurchases(), api.listCableTypes(), api.listAccessories()])
      .then(([page, types, accessoryList]) => {
        setPurchases(page.results);
        setCount(page.count);
        setNextPage(page.next ? 2 : null);
        setCableTypes(types);
        setAccessories(accessoryList);
      })
      .catch((err) => setError(err.message));

  useEffect(() => {
    load();
  }, []);

  const options = useMemo(() => buildOptions(cableTypes, accessories), [cableTypes, accessories]);

  async function loadMore() {
    setBusy(true);
    setError("");
    try {
      const page = await api.listPurchases({ page: nextPage });
      setPurchases((current) => [...current, ...page.results]);
      setNextPage(page.next ? nextPage + 1 : null);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function openForEdit(purchase) {
    setNotice("");
    setError("");
    try {
      setEditing(await api.getPurchase(purchase.id));
    } catch (err) {
      setError(err.message);
    }
  }

  async function remove(purchase) {
    if (!window.confirm("Delete this delivery? The cost it set will be recalculated from what's left.")) return;
    try {
      await api.deletePurchase(purchase.id);
      setNotice("Delivery deleted. Costs updated.");
      load();
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <div className="page">
      <CatalogueHeader
        action={!recording && !editing && (
          <button type="button" className="btn btn-primary" onClick={() => setRecording(true)}>Record purchase</button>
        )} />

      {error && <div className="alert alert-error">{error}</div>}
      {notice && <div className="alert alert-success">{notice}</div>}

      {recording || editing ? (
        <PurchaseForm key={editing?.id ?? "new"} options={options} purchase={editing}
          onClose={() => {
            setRecording(false);
            setEditing(null);
          }}
          onSaved={() => {
            setNotice(editing ? "Delivery updated. Costs recalculated." : "Delivery recorded. Your catalogue costs and margins are updated.");
            setRecording(false);
            setEditing(null);
            load();
          }} />
      ) : purchases === null ? (
        !error && <p className="muted">Loading…</p>
      ) : purchases.length === 0 ? (
        <div className="empty">
          No deliveries recorded yet. Enter what you paid for your stock and every quote will show the margin on it.
        </div>
      ) : (
        <>
          <div className="panel flush purchase-rows">
            {purchases.map((purchase) => (
              <PurchaseRow key={purchase.id} purchase={purchase}
                onEdit={() => openForEdit(purchase)} onDelete={() => remove(purchase)} />
            ))}
          </div>
          {nextPage && (
            <div className="load-more">
              <button type="button" className="btn btn-secondary" onClick={loadMore} disabled={busy}>
                {busy ? "Loading…" : `Load more (${count - purchases.length} left)`}
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
