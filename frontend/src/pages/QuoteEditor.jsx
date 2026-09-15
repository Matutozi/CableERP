import { useEffect, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import Field from "../components/Field.jsx";
import Icon from "../components/Icon.jsx";
import LineItemCard from "../components/LineItemCard.jsx";
import MoneyInput from "../components/MoneyInput.jsx";
import { useAuth } from "../context/AuthContext.jsx";
import useMediaQuery from "../hooks/useMediaQuery.js";
import { api } from "../services/api.js";
import { formatDate, formatNaira, formatPercent, isFractionalUnit, todayIso, toNumber, unitLabel } from "../services/format.js";
import { DEFAULT_COLOURS, coloursFor, findCableType, marginTotals, quoteTotals, unitCostFor } from "../services/quoteMath.js";

const BLANK_FIELDS = {
  customer_name: "",
  date: "",
  staff_name: "",
  staff_phone: "",
  product_manufacturer: "",
  transport_cost: "0",
  vat_percentage: "0",
  notes: "",
  status: "draft",
};

function pickFields(quote) {
  const fields = Object.fromEntries(Object.keys(BLANK_FIELDS).map((key) => [key, quote[key] ?? ""]));
  return { ...fields, transport_cost: String(toNumber(quote.transport_cost)), vat_percentage: String(toNumber(quote.vat_percentage)) };
}

let nextKey = 1;

function blankItem(kind) {
  return {
    key: nextKey++,
    kind,
    cable_size: null,
    accessory: null,
    cable_type_name: "",
    size_label: "",
    item_name: "",
    unit: kind === "cable" ? "coil" : "piece",
    unit_price: "",
    quoteByColour: false,
    quantities: {},
  };
}

/** Saved line item -> editable card state. Quantities are keyed by colour ("" when there are no colours). */
function fromLineItem(line) {
  return {
    key: nextKey++,
    kind: line.kind,
    cable_size: line.cable_size,
    accessory: line.accessory,
    cable_type_name: line.cable_type_name,
    size_label: line.size_label,
    item_name: line.item_name,
    unit: line.unit,
    unit_price: String(toNumber(line.unit_price)),
    quoteByColour: line.colours.some((entry) => entry.colour),
    quantities: Object.fromEntries(line.colours.map((entry) => [entry.colour, String(toNumber(entry.quantity))])),
  };
}

function itemProblem(item) {
  const name = item.kind === "cable" ? item.cable_type_name : item.item_name;
  if (!name.trim()) return item.kind === "cable" ? "Enter or pick a cable type." : "Enter or pick an accessory.";
  if (item.unit_price === "") return "Enter a unit price.";
  if (!item.colours.length) return "Enter a quantity.";
  const quantities = item.colours.map((entry) => toNumber(entry.quantity));
  if (!isFractionalUnit(item.unit) && quantities.some((qty) => !Number.isInteger(qty))) {
    return `Quantities in ${unitLabel(item.unit)} must be whole numbers.`;
  }
  if (quantities.some((qty) => Math.abs(qty * 100 - Math.round(qty * 100)) > 1e-9)) return "Use at most two decimal places.";
  return null;
}

// Remount per quote so switching from an existing quote to "new" starts from a clean form.
export default function QuoteEditorPage() {
  const { id } = useParams();
  return <QuoteEditor key={id ?? "new"} quoteId={id} />;
}

function QuoteEditor({ quoteId }) {
  const { user } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const isDesktop = useMediaQuery("(min-width: 768px)"); // same breakpoint as index.css

  const [cableTypes, setCableTypes] = useState([]);
  const [accessories, setAccessories] = useState([]);
  const [fields, setFields] = useState(null);
  const [items, setItems] = useState([]);
  const [itemErrors, setItemErrors] = useState({});
  const [focusKey, setFocusKey] = useState(null);
  const [saved, setSaved] = useState(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState(location.state?.notice ?? "");

  useEffect(() => {
    let cancelled = false;
    Promise.all([api.listCableTypes(), api.listAccessories(), api.getProfile(), quoteId ? api.getQuote(quoteId) : null])
      .then(([types, accessoryList, profile, quote]) => {
        if (cancelled) return;
        setCableTypes(types);
        setAccessories(accessoryList);
        if (quote) {
          applySaved(quote);
        } else {
          setFields({ ...BLANK_FIELDS, date: todayIso(), staff_name: user.full_name ?? "", vat_percentage: String(toNumber(profile.vat_rate)) });
          setItems([blankItem("cable")]);
        }
      })
      .catch((err) => !cancelled && setError(err.message));
    return () => {
      cancelled = true;
    };
  }, [quoteId, user.full_name]);

  function applySaved(quote) {
    setSaved(quote);
    setFields(pickFields(quote));
    setItems(quote.line_items.map(fromLineItem));
    setItemErrors({});
  }

  if (!fields) {
    return <div className="page">{error ? <div className="alert alert-error">{error}</div> : <p className="muted">Loading…</p>}</div>;
  }

  const resolved = items.map((item) => {
    const cableType = item.kind === "cable" ? findCableType(cableTypes, item.cable_type_name) : null;
    return {
      ...item,
      colours: coloursFor(item, cableType),
      // Read live from the catalogue while editing; the server freezes its own copy on save.
      unitCost: unitCostFor(item, cableType, accessories),
    };
  });
  const totals = quoteTotals(resolved, fields.vat_percentage, fields.transport_cost);
  const margin = marginTotals(resolved, totals.subtotal);
  // A sent quote is the record of what the customer received, so it is read-only until revised.
  const locked = saved?.status === "sent";
  const setField = (name) => (event) => setFields({ ...fields, [name]: event.target.value });

  function addItem(kind) {
    const item = blankItem(kind);
    setItems([...items, item]);
    setFocusKey(item.key);
  }

  function updateItem(key, patch) {
    setItems((current) => current.map((item) => (item.key === key ? { ...item, ...patch } : item)));
    if (itemErrors[key]) {
      const { [key]: _cleared, ...rest } = itemErrors;
      setItemErrors(rest);
      if (!Object.keys(rest).length) setError(""); // the "items need attention" banner no longer applies
    }
  }

  async function save() {
    const problems = Object.fromEntries(resolved.map((item) => [item.key, itemProblem(item)]).filter(([, problem]) => problem));
    setItemErrors(problems);
    if (!fields.customer_name.trim()) throw new Error("Enter the customer's name.");
    if (!fields.staff_name.trim()) throw new Error("Enter who prepared the quote.");
    if (!items.length) throw new Error("Add at least one item.");
    if (Object.keys(problems).length) throw new Error("Some items need attention. See the highlighted cards.");

    const payload = {
      ...fields,
      transport_cost: toNumber(fields.transport_cost).toFixed(2),
      vat_percentage: toNumber(fields.vat_percentage).toFixed(2),
      line_items: resolved.map((item) => {
        const isCable = item.kind === "cable";
        return {
          kind: item.kind,
          cable_size: isCable ? item.cable_size : null,
          accessory: isCable ? null : item.accessory,
          cable_type_name: isCable ? item.cable_type_name.trim() : "",
          size_label: isCable ? item.size_label.trim() : "",
          item_name: isCable ? "" : item.item_name.trim(),
          unit: item.unit,
          unit_price: toNumber(item.unit_price).toFixed(2),
          colours: item.colours,
        };
      }),
    };
    const quote = saved ? await api.updateQuote(saved.id, payload) : await api.createQuote(payload);
    applySaved(quote);
    return quote;
  }

  async function saveThen(action, after) {
    setBusy(action);
    setError("");
    setNotice("");
    try {
      after(await save());
    } catch (err) {
      setError(err.message);
      window.scrollTo({ top: 0, behavior: "smooth" });
    } finally {
      setBusy("");
    }
  }

  const handleSaveDraft = () =>
    saveThen("save", (quote) => {
      const message = `Saved ${quote.reference_number}.`;
      // A brand-new quote moves to its own URL so a refresh or "back" finds it again.
      if (quoteId) setNotice(message);
      else navigate(`/quotes/${quote.id}`, { replace: true, state: { notice: message } });
    });

  const handleGeneratePdf = () =>
    saveThen("pdf", (quote) => {
      if (!quoteId) navigate(`/quotes/${quote.id}`, { replace: true });
      navigate(`/quotes/${quote.id}/preview`);
    });

  /** Save a typed-in line to the catalogue at the price on the line, so next time it is a pick. */
  async function addToCatalogue(item) {
    setBusy(`catalogue-${item.key}`);
    setError("");
    setNotice("");
    const price = toNumber(item.unit_price).toFixed(2);
    try {
      if (item.kind === "accessory") {
        const created = await api.createAccessory({ name: item.item_name.trim(), unit: item.unit, default_price: price });
        setAccessories((current) => [...current, created]);
        updateItem(item.key, { accessory: created.id, item_name: created.name });
        setNotice(`${created.name} added to your accessories at ₦${formatNaira(created.default_price)}.`);
        return;
      }
      let cableType = findCableType(cableTypes, item.cable_type_name);
      let types = cableTypes;
      if (!cableType) {
        cableType = await api.createCableType({
          name: item.cable_type_name.trim(),
          unit: item.unit,
          has_colour_variants: item.quoteByColour,
          colour_options: item.quoteByColour ? DEFAULT_COLOURS : [],
        });
        types = [...cableTypes, cableType];
      }
      const size = await api.createSize(cableType.id, { size_label: item.size_label.trim(), default_price: price });
      const withSize = { ...cableType, sizes: [...(cableType.sizes ?? []), size] };
      setCableTypes(types.map((entry) => (entry.id === withSize.id ? withSize : entry)));
      updateItem(item.key, { cable_size: size.id, cable_type_name: cableType.name, size_label: size.size_label });
      setNotice(`${size.size_label} ${cableType.name} added to your catalogue at ₦${formatNaira(size.default_price)}.`);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy("");
    }
  }

  async function handleRevise() {
    setBusy("revise");
    setError("");
    try {
      const revision = await api.reviseQuote(saved.id);
      navigate(`/quotes/${revision.id}`, {
        state: { notice: `${revision.reference_number} is a revision of ${saved.reference_number}. Edit and send it as usual.` },
      });
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy("");
    }
  }

  async function handleDelete() {
    if (!window.confirm(`Delete quote ${saved.reference_number}? This cannot be undone.`)) return;
    try {
      await api.deleteQuote(saved.id);
      navigate("/quotes", { replace: true });
    } catch (err) {
      setError(err.message);
    }
  }

  const actionButtons = locked ? (
    <>
      <Link className="btn btn-secondary" to={`/quotes/${saved.id}/preview`}>Open preview</Link>
      <button type="button" className="btn btn-primary" onClick={handleRevise} disabled={!!busy}>
        {busy === "revise" ? "Creating…" : "Create revision"}
      </button>
    </>
  ) : (
    <>
      <button type="button" className="btn btn-outline" onClick={handleSaveDraft} disabled={!!busy}>
        {busy === "save" ? "Saving…" : "Save draft"}
      </button>
      <button type="button" className="btn btn-primary" onClick={handleGeneratePdf} disabled={!!busy}>
        {busy === "pdf" ? "Generating…" : "Generate PDF"}
      </button>
    </>
  );

  // Desktop pins this breakdown in the totals bar; phones show it in the page so the pinned bar stays short.
  const figures = (
    <div className="totals-figures">
      <div className="t-row">
        <span>Subtotal</span>
        <span className="num">₦{formatNaira(totals.subtotal)}</span>
      </div>
      <div className="t-row">
        <label className="t-vat">
          VAT
          <input className="mini-input vat-input" inputMode="decimal" value={fields.vat_percentage} aria-label="VAT percentage"
            disabled={locked}
            onChange={(event) => setFields({ ...fields, vat_percentage: event.target.value.replace(/[^\d.]/g, "") })} />
          %
        </label>
        <span className="num">{totals.vat ? `₦${formatNaira(totals.vat)}` : "–"}</span>
      </div>
      <div className="t-row">
        <span>Transport</span>
        <MoneyInput className="mini-input" value={fields.transport_cost} aria-label="Transport cost" disabled={locked}
          onChange={(value) => setFields({ ...fields, transport_cost: value })} />
      </div>
      {margin.known && (
        <div className={margin.margin < 0 ? "t-row t-margin loss" : "t-row t-margin"}>
          <span>
            Margin
            {margin.costedItems < margin.totalItems && (
              <span className="t-coverage"> on {margin.costedItems} of {margin.totalItems}</span>
            )}
          </span>
          <span className="num">
            {margin.margin < 0 ? "−" : ""}₦{formatNaira(Math.abs(margin.margin))} · {formatPercent(margin.percentage)}
          </span>
        </div>
      )}
    </div>
  );

  return (
    <div className="builder">
      <div className="builder-body">
        <div className="page-head">
          <div>
            <h1>{saved ? saved.reference_number : "New quote"}</h1>
            <div className="page-sub">
              {fields.status === "sent" ? "Sent" : "Draft"} · {saved ? `Created ${formatDate(saved.created_at)}` : "Not saved yet"}
              {saved?.revision_of_reference && ` · Revision of ${saved.revision_of_reference}`}
            </div>
          </div>
          {isDesktop && <div className="page-actions">{actionButtons}</div>}
        </div>

        {error && <div className="alert alert-error">{error}</div>}
        {notice && <div className="alert alert-success">{notice}</div>}
        {locked && (
          <div className="alert alert-info">
            Sent{saved.sent_at ? ` on ${formatDate(saved.sent_at)}` : ""}. This is the record of what the customer
            received, so it can't be changed — create a revision to quote them again.
          </div>
        )}

        <fieldset className="editor-fields" disabled={locked}>
          <section className="panel">
            <div className="field-grid">
              <Field label="Customer">
                <input value={fields.customer_name} onChange={setField("customer_name")} placeholder="Customer name" />
              </Field>
              <Field label="Prepared by">
                <input value={fields.staff_name} onChange={setField("staff_name")} />
              </Field>
              <Field label="Date">
                <input type="date" value={fields.date} onChange={setField("date")} />
              </Field>
              <Field label={<>Manufacturer <span className="optional">(optional)</span></>}>
                <input value={fields.product_manufacturer} onChange={setField("product_manufacturer")} placeholder="e.g. Coleman Wires and Cables" />
              </Field>
            </div>
            <details className="more">
              <summary>More details</summary>
              <div className="field-grid">
                <Field label={<>Staff phone <span className="optional">(optional)</span></>}>
                  <input type="tel" value={fields.staff_phone} onChange={setField("staff_phone")} />
                </Field>
                <Field label="Status">
                  <select value={fields.status} onChange={setField("status")}>
                    <option value="draft">Draft</option>
                    <option value="sent">Sent</option>
                  </select>
                </Field>
                <Field label={<>Notes <span className="optional">(printed at the bottom)</span></>} wide>
                  <textarea rows={2} value={fields.notes} onChange={setField("notes")} />
                </Field>
              </div>
              {saved && (
                <button type="button" className="btn-link btn-link-danger" onClick={handleDelete}>Delete this quote</button>
              )}
            </details>
          </section>


          <div className="section-head">
            <h2>Items</h2>
            <span className="muted small">{items.length} {items.length === 1 ? "item" : "items"}</span>
          </div>

          {items.length === 0 ? (
            <div className="empty">No items yet. Add a cable or an accessory below.</div>
          ) : (
            <div className="item-list">
              {resolved.map((item) => (
                <LineItemCard key={item.key} item={item} cableTypes={cableTypes} accessories={accessories}
                  unitCost={item.unitCost}
                  error={itemErrors[item.key]} autoFocus={item.key === focusKey}
                  adding={busy === `catalogue-${item.key}`}
                  onChange={(patch) => updateItem(item.key, patch)}
                  onAddToCatalogue={() => addToCatalogue(item)}
                  onRemove={() => setItems((current) => current.filter((entry) => entry.key !== item.key))} />
              ))}
            </div>
          )}

          <div className="add-row">
            <button type="button" className="btn-link" onClick={() => addItem("cable")}>
              <Icon name="plus" size={15} strokeWidth={1.7} />Add cable
            </button>
            <button type="button" className="btn-link" onClick={() => addItem("accessory")}>
              <Icon name="plus" size={15} strokeWidth={1.7} />Add accessory
            </button>
          </div>

          {!isDesktop && <section className="panel charges">{figures}</section>}
        </fieldset>
      </div>

      <div className="totals-bar">
        <div className="totals-line">
          {isDesktop && figures}
          <div className="grand">
            <span>Grand total</span>
            <strong>₦{formatNaira(totals.grandTotal)}</strong>
          </div>
        </div>
        {!isDesktop && <div className="bar-actions">{actionButtons}</div>}
      </div>
    </div>
  );
}
