import { api } from "./api.js";

// Each document type knows how to fetch its PDF and what the file is called.
const DOCUMENTS = {
  quote: { fetch: (doc) => api.quotePdf(doc.id), title: (doc) => `Quotation ${doc.reference_number}` },
  waybill: { fetch: (doc) => api.waybillPdf(doc.id), title: (doc) => `Waybill ${doc.reference_number}` },
};

async function fetchPdf(kind, doc) {
  const response = await DOCUMENTS[kind].fetch(doc);
  const blob = await response.blob();
  return new File([blob], `${doc.reference_number}.pdf`, { type: "application/pdf" });
}

function saveFile(file) {
  const url = URL.createObjectURL(file);
  const link = document.createElement("a");
  link.href = url;
  link.download = file.name;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

/** True where the browser can hand a PDF to WhatsApp, email etc. (mostly phones). */
export function canShareFiles() {
  if (typeof navigator.canShare !== "function") return false;
  return navigator.canShare({ files: [new File([""], "document.pdf", { type: "application/pdf" })] });
}

async function share(kind, doc, text) {
  const file = await fetchPdf(kind, doc);
  try {
    await navigator.share({ files: [file], title: DOCUMENTS[kind].title(doc), text });
    return "shared";
  } catch (error) {
    if (error.name === "AbortError") return "cancelled";
    saveFile(file);
    return "downloaded";
  }
}

export const downloadQuotePdf = async (quote) => saveFile(await fetchPdf("quote", quote));
export const downloadWaybillPdf = async (waybill) => saveFile(await fetchPdf("waybill", waybill));

/**
 * Open the phone's share sheet with the PDF attached.
 * Returns "shared", "cancelled", or "downloaded" when the browser refuses to share
 * (some, notably iOS Safari, won't share after a slow network fetch).
 */
export const shareQuotePdf = (quote, text) => share("quote", quote, text);
export const shareWaybillPdf = (waybill, text) => share("waybill", waybill, text);
