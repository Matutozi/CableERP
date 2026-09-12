const nairaFormat = new Intl.NumberFormat("en-NG", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const plainFormat = new Intl.NumberFormat("en-NG", { maximumFractionDigits: 2 });

// Mirrors QUOTE_UNITS / FRACTIONAL_UNITS in backend/catalogue/models.py.
const UNIT_NAMES = {
  coil: ["coil", "coils"],
  metre: ["metre", "metres"],
  piece: ["piece", "pieces"],
  pack: ["pack", "packs"],
  box: ["box", "boxes"],
  roll: ["roll", "rolls"],
  length: ["length", "lengths"],
  set: ["set", "sets"],
};
export const CABLE_UNITS = [["coil", "Coil (100m)"], ["metre", "Metre"]];
export const ACCESSORY_UNITS = [
  ["piece", "Piece"],
  ["pack", "Pack"],
  ["box", "Box"],
  ["roll", "Roll"],
  ["length", "Length"],
  ["set", "Set"],
  ["metre", "Metre"],
];
export const isFractionalUnit = (unit) => unit === "metre";

export function toNumber(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : 0;
}

export const round2 = (value) => Math.round((value + Number.EPSILON) * 100) / 100;

/** 2277000 -> "2,277,000.00" (no currency sign; callers add ₦ where it reads better). */
export const formatNaira = (value) => nairaFormat.format(toNumber(value));

/** "30.00" -> "30", "12.50" -> "12.5". */
export const formatQty = (value) => plainFormat.format(toNumber(value));

export function unitLabel(unit, quantity = 2) {
  const [one, many] = UNIT_NAMES[unit] ?? [unit, `${unit}s`];
  return toNumber(quantity) === 1 ? one : many;
}

/** "2026-09-11" (or an ISO datetime) -> "11/09/2026". */
export function formatDate(iso) {
  if (!iso) return "";
  const [year, month, day] = iso.slice(0, 10).split("-");
  return `${day}/${month}/${year}`;
}

/** "2026-09-12T14:32:10Z" -> "12/09/2026 14:32" in the viewer's own time. */
export function formatDateTime(iso) {
  if (!iso) return "";
  const when = new Date(iso);
  const pad = (value) => String(value).padStart(2, "0");
  return `${pad(when.getDate())}/${pad(when.getMonth() + 1)}/${when.getFullYear()} ${pad(when.getHours())}:${pad(when.getMinutes())}`;
}

export function todayIso() {
  const now = new Date();
  return new Date(now.getTime() - now.getTimezoneOffset() * 60_000).toISOString().slice(0, 10);
}
