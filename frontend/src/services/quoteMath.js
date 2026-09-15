// Catalogue matching and running totals for the quote builder. The server recomputes everything on save,
// and its figures are what appear on the PDF.
import { round2, toNumber } from "./format.js";

export const DEFAULT_COLOURS = ["Red", "Black", "Yellow/Green"];

const same = (a, b) => a.trim().toLowerCase() === b.trim().toLowerCase();

export const findCableType = (cableTypes, name) =>
  name?.trim() ? cableTypes.find((type) => same(type.name, name)) ?? null : null;

export const findSize = (cableType, label) =>
  cableType && label?.trim() ? cableType.sizes.find((size) => same(size.size_label, label)) ?? null : null;

export const findAccessory = (accessories, name) =>
  name?.trim() ? accessories.find((accessory) => same(accessory.name, name)) ?? null : null;

/**
 * Colour rows a cable card shows: the catalogue type's colours (or the default set for a cable that
 * isn't in the catalogue but is quoted by colour), plus any other colour already holding a quantity.
 * An empty list means the item takes a single quantity.
 */
export function colourNamesFor(item, cableType) {
  if (item.kind !== "cable") return [];
  let base = [];
  if (cableType) base = cableType.has_colour_variants ? cableType.colour_options : [];
  else if (item.quoteByColour) base = DEFAULT_COLOURS;
  const extra = Object.keys(item.quantities).filter(
    (name) => name && !base.includes(name) && toNumber(item.quantities[name]) > 0,
  );
  return [...base, ...extra];
}

/** The colour/quantity rows to save for an item — only those with a quantity. */
export function coloursFor(item, cableType) {
  const names = colourNamesFor(item, cableType);
  return (names.length ? names : [""])
    .map((colour) => ({ colour, quantity: toNumber(item.quantities[colour]) }))
    .filter((entry) => entry.quantity > 0)
    .map((entry) => ({ colour: entry.colour, quantity: String(entry.quantity) }));
}

export function lineTotals(item) {
  const quantity = item.colours.reduce((sum, entry) => sum + toNumber(entry.quantity), 0);
  return { quantity, amount: round2(quantity * toNumber(item.unit_price)) };
}

export function quoteTotals(items, vatPercentage, transportCost) {
  const subtotal = round2(items.reduce((sum, item) => sum + lineTotals(item).amount, 0));
  const vat = round2((subtotal * toNumber(vatPercentage)) / 100);
  const transport = toNumber(transportCost);
  return { subtotal, vat, transport, grandTotal: round2(subtotal + vat + transport) };
}

/**
 * What this line's stock cost, per unit, from the catalogue — or null if no purchase has ever
 * been recorded for it. The server re-reads this and freezes it onto the quote when it saves;
 * this copy only keeps the running figures honest while the seller is still typing.
 */
export function unitCostFor(item, cableType, accessories) {
  const row = item.kind === "cable" ? findSize(cableType, item.size_label) : findAccessory(accessories, item.item_name);
  return row?.last_unit_cost ?? null;
}

/**
 * Margin across a quote, counting only the lines whose cost is known and saying how much of
 * the quote that covers. An unknown cost is never treated as zero: that would report a 100%
 * margin on everything nobody has costed yet, which is worse than reporting nothing.
 */
export function marginTotals(items, subtotal) {
  const costed = items.filter((item) => item.unitCost !== null && item.unitCost !== undefined);
  if (!costed.length) {
    return { known: false, cost: 0, margin: 0, percentage: null, costedItems: 0, totalItems: items.length, valueShare: 0 };
  }
  const revenue = round2(costed.reduce((sum, item) => sum + lineTotals(item).amount, 0));
  const cost = round2(costed.reduce((sum, item) => sum + lineTotals(item).quantity * toNumber(item.unitCost), 0));
  return {
    known: true,
    cost,
    margin: round2(revenue - cost),
    percentage: revenue > 0 ? round2(((revenue - cost) / revenue) * 100) : null,
    costedItems: costed.length,
    totalItems: items.length,
    valueShare: subtotal > 0 ? round2((revenue / subtotal) * 100) : 0,
  };
}
