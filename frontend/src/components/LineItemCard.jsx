import {
  ACCESSORY_UNITS,
  CABLE_UNITS,
  formatNaira,
  formatQty,
  isFractionalUnit,
  toNumber,
  unitLabel,
} from "../services/format.js";
import {
  DEFAULT_COLOURS,
  colourNamesFor,
  coloursFor,
  findAccessory,
  findCableType,
  findSize,
  lineTotals,
} from "../services/quoteMath.js";
import Combobox from "./Combobox.jsx";
import Icon from "./Icon.jsx";
import MoneyInput from "./MoneyInput.jsx";

const DOT_COLOURS = {
  red: "#DC2626",
  black: "#111111",
  "yellow/green": "#CA8A04",
  yellow: "#EAB308",
  green: "#16A34A",
  blue: "#2563EB",
  brown: "#92400E",
  grey: "#6B7280",
  gray: "#6B7280",
  white: "#FFFFFF",
  orange: "#EA580C",
};
const dotColour = (name) => DOT_COLOURS[name.trim().toLowerCase()] ?? "#A3A3A3";

/** "Red", "Black", "Yellow/Green" -> "R", "B", "Y/G"; falls back to full names if two would clash. */
function shortNames(names) {
  const short = names.map((name) => name.split("/").map((part) => part.trim()[0]?.toUpperCase() ?? "").join("/"));
  return new Set(short).size === short.length ? short : names;
}

const onlyAmount = (text) => text.replace(/[^\d.]/g, "");

/**
 * One editable quote line, per the prototype's "cards" layout: type or pick a cable (then size) or an
 * accessory from the catalogue; anything not in the catalogue is quoted exactly as typed.
 */
export default function LineItemCard({ item, cableTypes, accessories, error, autoFocus, adding, onChange, onRemove, onAddToCatalogue }) {
  const isCable = item.kind === "cable";
  const cableType = isCable ? findCableType(cableTypes, item.cable_type_name) : null;
  const accessory = isCable ? null : findAccessory(accessories, item.item_name);
  const name = isCable ? item.cable_type_name : item.item_name;
  const custom = name.trim() !== "" && !(cableType || accessory);
  const knownSize = isCable ? findSize(cableType, item.size_label) : null;
  // Either the type/accessory is unknown, or the type is known but this is a new size under it.
  const newToCatalogue = isCable
    ? Boolean(item.cable_type_name.trim() && item.size_label.trim() && !knownSize)
    : Boolean(item.item_name.trim() && !accessory);
  const colourNames = colourNamesFor(item, cableType);
  const labels = shortNames(colourNames);
  const { quantity, amount } = lineTotals({ unit_price: item.unit_price, colours: coloursFor(item, cableType) });
  const qtyMode = isFractionalUnit(item.unit) ? "decimal" : "numeric";

  const setQuantity = (colour) => (event) =>
    onChange({ quantities: { ...item.quantities, [colour]: onlyAmount(event.target.value) } });

  function pickCableType(value) {
    const match = findCableType(cableTypes, value);
    if (!match) return onChange({ cable_type_name: value, cable_size: null });
    const size = findSize(match, item.size_label) ?? match.sizes[0] ?? null;
    const namedColours = Object.keys(item.quantities).some((colour) => colour);
    onChange({
      cable_type_name: match.name,
      unit: match.unit,
      size_label: size?.size_label ?? item.size_label,
      cable_size: size?.id ?? null,
      ...(size && { unit_price: String(toNumber(size.default_price)) }),
      // Colour quantities only carry over to a type that is also sold by colour.
      ...(!match.has_colour_variants && namedColours && { quantities: { "": item.quantities[""] ?? "" } }),
    });
  }

  function pickSize(value) {
    const size = findSize(cableType, value);
    onChange({ size_label: value, cable_size: size?.id ?? null, ...(size && { unit_price: String(toNumber(size.default_price)) }) });
  }

  function pickAccessory(value) {
    const match = findAccessory(accessories, value);
    if (!match) return onChange({ item_name: value, accessory: null });
    onChange({ item_name: match.name, accessory: match.id, unit: match.unit, unit_price: String(toNumber(match.default_price)) });
  }

  function toggleByColour(event) {
    onChange(event.target.checked
      ? { quoteByColour: true }
      : { quoteByColour: false, quantities: { "": item.quantities[""] ?? "" } });
  }

  return (
    <div className={error ? "item-card has-error" : "item-card"}>
      {isCable ? (
        <div className="item-row">
          <div className="grow">
            <span className="field-label">Cable type</span>
            <Combobox value={item.cable_type_name} ariaLabel="Cable type" placeholder="Pick or type a cable"
              autoFocus={autoFocus} onChange={pickCableType}
              options={cableTypes.map((type) => ({
                value: type.name,
                hint: `${type.sizes.length} ${type.sizes.length === 1 ? "size" : "sizes"} · per ${unitLabel(type.unit, 1)}`,
              }))} />
          </div>
          <div className="w-size">
            <span className="field-label">Size</span>
            <Combobox value={item.size_label} ariaLabel="Size" placeholder="Size" onChange={pickSize}
              options={(cableType?.sizes ?? []).map((size) => ({ value: size.size_label }))} />
          </div>
        </div>
      ) : (
        <div className="item-row">
          <div className="grow">
            <span className="field-label">Accessory</span>
            <Combobox value={item.item_name} ariaLabel="Accessory" placeholder="Pick or type an accessory"
              autoFocus={autoFocus} onChange={pickAccessory}
              options={accessories.map((accessory) => ({
                value: accessory.name,
                hint: `₦${formatNaira(accessory.default_price)} / ${unitLabel(accessory.unit, 1)}`,
              }))} />
          </div>
        </div>
      )}

      {custom && (
        <div className="item-custom">
          <label className="unit-select">
            <span>Sold per</span>
            <select value={item.unit} onChange={(event) => onChange({ unit: event.target.value })}>
              {(isCable ? CABLE_UNITS : ACCESSORY_UNITS).map(([value, label]) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </select>
          </label>
          {isCable && (
            <label className="check">
              <input type="checkbox" checked={item.quoteByColour} onChange={toggleByColour} />
              Quote by colour ({DEFAULT_COLOURS.map((colour) => shortNames([colour])[0]).join(" / ")})
            </label>
          )}
        </div>
      )}

      {newToCatalogue && (
        <div className="catalogue-offer">
          <span className="field-hint">
            {custom
              ? "Not in your catalogue — quoted as typed."
              : `New size for ${cableType.name} — quoted as typed.`}
          </span>
          <button type="button" className="btn-link" disabled={adding || item.unit_price === ""}
            title={item.unit_price === "" ? "Enter a unit price first" : "Save it with this price for next time"}
            onClick={onAddToCatalogue}>
            <Icon name="plus" size={14} strokeWidth={1.7} />{adding ? "Adding…" : "Add to catalogue"}
          </button>
        </div>
      )}

      <div className="item-row">
        <label className="w-price">
          <span className="field-label">Unit price</span>
          <MoneyInput value={item.unit_price} placeholder="₦0.00" onChange={(value) => onChange({ unit_price: value })} />
        </label>
        {colourNames.length === 0 && (
          <label className="w-qty">
            <span className="field-label">Qty ({unitLabel(item.unit)})</span>
            <input type="text" inputMode={qtyMode} value={item.quantities[""] ?? ""} placeholder="0" onChange={setQuantity("")} />
          </label>
        )}
      </div>

      {colourNames.length > 0 && (
        <fieldset className="colour-qty">
          <legend className="field-label">Quantity by colour ({unitLabel(item.unit)})</legend>
          <div className="colour-grid">
            {colourNames.map((colour, index) => (
              <label key={colour} className="colour-input" title={colour}>
                <span className="dot" style={{ background: dotColour(colour) }} />
                <span className="colour-abbr">{labels[index]}</span>
                <input type="text" inputMode={qtyMode} value={item.quantities[colour] ?? ""} placeholder="0"
                  aria-label={`${colour} quantity`} onChange={setQuantity(colour)} />
              </label>
            ))}
          </div>
        </fieldset>
      )}

      {error && <div className="item-error">{error}</div>}

      <div className="item-foot">
        <button type="button" className="icon-btn icon-btn-danger" onClick={onRemove} title="Remove item" aria-label="Remove item">
          <Icon name="trash" size={15} />
        </button>
        <div className="item-sum">
          <span className="item-qty">{formatQty(quantity)} {unitLabel(item.unit, quantity)}</span>
          <span className="item-total">₦{formatNaira(amount)}</span>
        </div>
      </div>
    </div>
  );
}
