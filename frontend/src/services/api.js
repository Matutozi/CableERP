export const AUTH_EXPIRED_EVENT = "cableerp:auth-expired";

function getCookie(name) {
  const match = document.cookie.match(new RegExp(`(?:^|;\\s*)${name}=([^;]*)`));
  return match ? decodeURIComponent(match[1]) : null;
}

/**
 * Pull the first readable message out of a DRF error body, with the field path in front,
 * e.g. {line_items: [{}, {colours: ["Coil quantities must be whole numbers."]}]}
 *   -> "line items › #2 › colours: Coil quantities must be whole numbers."
 */
function firstError(data, path = []) {
  if (data == null) return null;
  if (typeof data === "string") return path.length ? `${path.join(" › ")}: ${data}` : data;
  if (Array.isArray(data)) {
    for (const [index, entry] of data.entries()) {
      // A list of objects holds per-row errors; a list of strings holds messages for one field.
      const isRow = typeof entry === "object" && entry !== null;
      const found = firstError(entry, isRow ? [...path, `#${index + 1}`] : path);
      if (found) return found;
    }
    return null;
  }
  for (const [key, value] of Object.entries(data)) {
    const label = key === "detail" || key === "non_field_errors" ? [] : [key.replaceAll("_", " ")];
    const found = firstError(value, [...path, ...label]);
    if (found) return found;
  }
  return null;
}

export class ApiError extends Error {
  constructor(status, data) {
    super(firstError(data) ?? `Request failed (${status}). Please try again.`);
    this.status = status;
    this.data = data;
  }
}

async function request(path, { method = "GET", body, raw = false } = {}) {
  const headers = {};
  if (method !== "GET") headers["X-CSRFToken"] = getCookie("csrftoken") ?? "";

  let payload;
  if (body instanceof FormData) {
    payload = body;
  } else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }

  const response = await fetch(`/api${path}`, { method, headers, body: payload, credentials: "same-origin" });
  if (!response.ok) {
    const data = await response.json().catch(() => null);
    if (response.status === 401) window.dispatchEvent(new Event(AUTH_EXPIRED_EVENT));
    throw new ApiError(response.status, data);
  }
  if (raw) return response;
  return response.status === 204 ? null : response.json();
}

const get = (path) => request(path);
const post = (path, body) => request(path, { method: "POST", body });
const put = (path, body) => request(path, { method: "PUT", body });
const patch = (path, body) => request(path, { method: "PATCH", body });
const del = (path) => request(path, { method: "DELETE" });

export const api = {
  me: () => get("/auth/me/"),
  login: (credentials) => post("/auth/login/", credentials),
  register: (details) => post("/auth/register/", details),
  logout: () => post("/auth/logout/"),
  logoutEverywhere: () => post("/auth/logout-everywhere/"),

  getProfile: () => get("/profile/"),
  updateProfile: (data) => put("/profile/", data),
  uploadLogo: (file) => {
    const form = new FormData();
    form.append("logo", file);
    return post("/profile/logo/", form);
  },
  removeLogo: () => del("/profile/logo/"),
  uploadBrandLogo: (file) => {
    const form = new FormData();
    form.append("brand_logo", file);
    return post("/profile/brand-logo/", form);
  },
  removeBrandLogo: () => del("/profile/brand-logo/"),
  listActivity: () => get("/activity/"),

  listCableTypes: () => get("/cable-types/"),
  priceMovements: () => get("/price-movements/"),
  createCableType: (data) => post("/cable-types/", data),
  updateCableType: (id, data) => put(`/cable-types/${id}/`, data),
  deleteCableType: (id) => del(`/cable-types/${id}/`),
  createSize: (cableTypeId, data) => post(`/cable-types/${cableTypeId}/sizes/`, data),
  updateSize: (id, data) => put(`/sizes/${id}/`, data),
  sizeHistory: (id) => get(`/sizes/${id}/history/`),
  deleteSize: (id) => del(`/sizes/${id}/`),

  listAccessories: () => get("/accessories/"),
  createAccessory: (data) => post("/accessories/", data),
  updateAccessory: (id, data) => put(`/accessories/${id}/`, data),
  accessoryHistory: (id) => get(`/accessories/${id}/history/`),
  deleteAccessory: (id) => del(`/accessories/${id}/`),

  listPurchases: ({ page = 1, pageSize } = {}) => {
    const params = new URLSearchParams({ page: String(page) });
    if (pageSize) params.set("page_size", String(pageSize));
    return get(`/purchases/?${params}`);
  },
  getPurchase: (id) => get(`/purchases/${id}/`),
  createPurchase: (data) => post("/purchases/", data),
  updatePurchase: (id, data) => put(`/purchases/${id}/`, data),
  deletePurchase: (id) => del(`/purchases/${id}/`),

  listQuotes: ({ search = "", page = 1, pageSize } = {}) => {
    const params = new URLSearchParams({ page: String(page) });
    if (search) params.set("search", search);
    if (pageSize) params.set("page_size", String(pageSize));
    return get(`/quotes/?${params}`);
  },
  getQuote: (id) => get(`/quotes/${id}/`),
  createQuote: (data) => post("/quotes/", data),
  updateQuote: (id, data) => put(`/quotes/${id}/`, data),
  patchQuote: (id, data) => patch(`/quotes/${id}/`, data),
  reviseQuote: (id) => post(`/quotes/${id}/revise/`),
  deleteQuote: (id) => del(`/quotes/${id}/`),
  quotePdf: (id) => request(`/quotes/${id}/pdf/`, { raw: true }),

  listWaybills: ({ quote, page = 1 } = {}) => {
    const params = new URLSearchParams({ page: String(page) });
    if (quote) params.set("quote", String(quote));
    return get(`/waybills/?${params}`);
  },
  createWaybill: (quoteId) => post("/waybills/", { quote: quoteId }),
  getWaybill: (id) => get(`/waybills/${id}/`),
  updateWaybill: (id, data) => put(`/waybills/${id}/`, data),
  deleteWaybill: (id) => del(`/waybills/${id}/`),
  waybillPdf: (id) => request(`/waybills/${id}/pdf/`, { raw: true }),
};
