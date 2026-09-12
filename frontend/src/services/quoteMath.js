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
