import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import Field from "../components/Field.jsx";
import Icon from "../components/Icon.jsx";
import { api } from "../services/api.js";
import { formatQty, isFractionalUnit, toNumber, unitLabel } from "../services/format.js";
import { canShareFiles, downloadWaybillPdf, shareWaybillPdf } from "../services/pdf.js";

const FIELDS = ["customer_name", "date", "invoice_number", "branch", "vehicle_number", "product_manufacturer", "notes"];

let nextKey = 1;

/** A saved line as editable state: quantities keyed by colour ("" for items not sold by colour). */
function toEditable(item) {
  return { ...item, key: nextKey++, quantities: Object.fromEntries(item.colours.map((entry) => [entry.colour, String(toNumber(entry.quantity))])) };
}

function toPayload(fields, items) {
  return {
    ...fields,
    items: items.map((item) => ({
      kind: item.kind,
      cable_size: item.cable_size,
      accessory: item.accessory,
      cable_type_name: item.cable_type_name,
      size_label: item.size_label,
      item_name: item.item_name,
      unit: item.unit,
      // A colour cut to nothing is left off this delivery rather than sent as zero.
      colours: Object.entries(item.quantities)
        .filter(([, quantity]) => toNumber(quantity) > 0)
        .map(([colour, quantity]) => ({ colour, quantity: String(toNumber(quantity)) })),
    })),
  };
}

function itemProblem(item) {
  const quantities = Object.values(item.quantities).map(toNumber);
  if (!quantities.some((quantity) => quantity > 0)) return "Enter a quantity, or remove this line from the waybill.";
  if (!isFractionalUnit(item.unit) && quantities.some((quantity) => !Number.isInteger(quantity))) {
    return `Quantities in ${unitLabel(item.unit)} must be whole numbers.`;
  }
  return null;
}

export default function WaybillEditor() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [waybill, setWaybill] = useState(null);
  const [fields, setFields] = useState(null);
  const [items, setItems] = useState([]);
  const [problems, setProblems] = useState({});
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  function apply(saved) {
    setWaybill(saved);
    setFields(Object.fromEntries(FIELDS.map((name) => [name, saved[name] ?? ""])));
    setItems(saved.items.map(toEditable));
    setProblems({});
  }

  useEffect(() => {
    api.getWaybill(id).then(apply).catch((err) => setError(err.message));
  }, [id]);

  if (!fields) {
    return <div className="page">{error ? <div className="alert alert-error">{error}</div> : <p className="muted">Loading…</p>}</div>;
  }

  const savedPayload = JSON.stringify(toPayload(Object.fromEntries(FIELDS.map((name) => [name, waybill[name] ?? ""])), waybill.items.map(toEditable)));
  const dirty = JSON.stringify(toPayload(fields, items)) !== savedPayload;
  const setField = (name) => (event) => setFields({ ...fields, [name]: event.target.value });
  const setQuantity = (key, colour, value) =>
    setItems((current) => current.map((item) => (item.key === key ? { ...item, quantities: { ...item.quantities, [colour]: value.replace(/[^\d.]/g, "") } } : item)));

  /** Save if anything changed, so the PDF always matches what is on screen. */
  async function save() {
    const found = Object.fromEntries(items.map((item) => [item.key, itemProblem(item)]).filter(([, problem]) => problem));
    setProblems(found);
    if (!fields.customer_name.trim()) throw new Error("Enter who the goods are going to.");
    if (!items.length) throw new Error("A waybill needs at least one item.");
    if (Object.keys(found).length) throw new Error("Some lines need attention. See the highlighted items.");
    if (!dirty) return waybill;
    const saved = await api.updateWaybill(waybill.id, toPayload(fields, items));
    apply(saved);
    return saved;
  }

  async function run(action, task) {
    setBusy(action);
    setError("");
    setNotice("");
    try {
      await task();
    } catch (err) {
      setError(err.message);
      window.scrollTo({ top: 0, behavior: "smooth" });
    } finally {
      setBusy("");
    }
  }

  const handleSave = () => run("save", async () => {
    await save();
    setNotice("Waybill saved.");
  });

  const handleDownload = () => run("download", async () => {
    const saved = await save();
    await downloadWaybillPdf(saved);
    setNotice(`Downloaded ${saved.reference_number}.pdf.`);
  });

  const handleShare = () => run("share", async () => {
    const saved = await save();
    const outcome = await shareWaybillPdf(saved, `Waybill ${saved.reference_number} for ${saved.customer_name}.`);
    if (outcome === "downloaded") setNotice("This browser couldn't open the share menu, so the PDF was downloaded.");
  });

  function handleDelete() {
    if (!window.confirm(`Delete waybill ${waybill.reference_number}? This cannot be undone.`)) return;
    run("delete", async () => {
      await api.deleteWaybill(waybill.id);
      navigate("/quotes/waybills", { replace: true });
    });
  }

  const actions = (
    <>
      <button type="button" className="btn btn-outline" onClick={handleSave} disabled={!!busy || !dirty}>
        {busy === "save" ? "Saving…" : dirty ? "Save" : "Saved"}
      </button>
      {canShareFiles() && (
        <button type="button" className="btn btn-secondary" onClick={handleShare} disabled={!!busy}>
          {busy === "share" ? "Preparing…" : "Share"}
        </button>
      )}
      <button type="button" className="btn btn-primary" onClick={handleDownload} disabled={!!busy}>
        {busy === "download" ? "Preparing…" : "Download PDF"}
      </button>
    </>
  );

  return (
    <div className="page waybill-editor">
      <div className="page-head">
        <div>
          <h1>{waybill.reference_number}</h1>
          <div className="page-sub">
            Waybill
            {waybill.quote ? <> · from <Link to={`/quotes/${waybill.quote}`}>{waybill.quote_reference}</Link></> : " · quote since deleted"}
          </div>
        </div>
        <div className="page-actions">{actions}</div>
      </div>

      {error && <div className="alert alert-error">{error}</div>}
      {notice && <div className="alert alert-success">{notice}</div>}

      <section className="panel">
        <div className="field-grid">
          <Field label="M/S (customer)">
            <input value={fields.customer_name} onChange={setField("customer_name")} />
          </Field>
          <Field label="Date">
            <input type="date" value={fields.date} onChange={setField("date")} />
          </Field>
          <Field label="Invoice No" hint="Starts as the quote's reference. Change it to your invoice number if you have one.">
            <input value={fields.invoice_number} onChange={setField("invoice_number")} />
          </Field>
          <Field label={<>Branch <span className="optional">(optional)</span></>}>
            <input value={fields.branch} onChange={setField("branch")} placeholder="e.g. Arepo" />
          </Field>
          <Field label={<>Vehicle No <span className="optional">(optional)</span></>}>
            <input value={fields.vehicle_number} onChange={setField("vehicle_number")} placeholder="e.g. LSD 482 KJ" autoCapitalize="characters" />
          </Field>
          <Field label={<>Product of <span className="optional">(optional)</span></>}>
            <input value={fields.product_manufacturer} onChange={setField("product_manufacturer")} placeholder="e.g. Coleman Wires and Cables" />
          </Field>
          <Field label={<>Notes <span className="optional">(optional)</span></>} wide>
            <textarea rows={2} value={fields.notes} onChange={setField("notes")} />
          </Field>
        </div>
      </section>

      <div className="section-head">
        <h2>Items</h2>
        <span className="muted small">Lower a quantity for a part delivery</span>
      </div>

      <div className="item-list">
        {items.map((item) => {
          const colours = Object.keys(item.quantities);
          const byColour = colours.some((colour) => colour);
          const total = Object.values(item.quantities).reduce((sum, quantity) => sum + toNumber(quantity), 0);
          const mode = isFractionalUnit(item.unit) ? "decimal" : "numeric";
          return (
            <div key={item.key} className={problems[item.key] ? "item-card has-error" : "item-card"}>
              <div className="waybill-item-head">
                <span>
                  {item.model_label && <span className="waybill-model">{item.model_label}</span>}
                  <span className="waybill-desc">{item.description}</span>
                </span>
                <button type="button" className="icon-btn icon-btn-danger" aria-label={`Remove ${item.description}`}
                  onClick={() => setItems((current) => current.filter((entry) => entry.key !== item.key))}>
                  <Icon name="trash" size={15} />
                </button>
              </div>
              {byColour ? (
                <div className="colour-grid">
                  {colours.map((colour) => (
                    <label key={colour} className="colour-input">
                      <span className="colour-abbr">{colour}</span>
                      <input type="text" inputMode={mode} value={item.quantities[colour]} aria-label={`${colour} quantity`}
                        onChange={(event) => setQuantity(item.key, colour, event.target.value)} />
                    </label>
                  ))}
                </div>
              ) : (
                <label className="w-qty">
                  <span className="field-label">Qty ({unitLabel(item.unit)})</span>
                  <input type="text" inputMode={mode} value={item.quantities[""] ?? ""} aria-label={`Quantity of ${item.description}`}
                    onChange={(event) => setQuantity(item.key, "", event.target.value)} />
                </label>
              )}
              {problems[item.key] && <div className="item-error">{problems[item.key]}</div>}
              <div className="item-foot">
                <span />
                <span className="item-qty">{formatQty(total)} {unitLabel(item.unit, total)}</span>
              </div>
            </div>
          );
        })}
      </div>

      <div className="waybill-foot">
        <button type="button" className="btn-link btn-link-danger" onClick={handleDelete} disabled={!!busy}>Delete this waybill</button>
      </div>
    </div>
  );
}
