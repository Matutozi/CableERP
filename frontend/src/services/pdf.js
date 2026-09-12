import { api } from "./api.js";

async function fetchQuotePdf(quote) {
  const response = await api.quotePdf(quote.id);
  const blob = await response.blob();
  return new File([blob], `${quote.reference_number}.pdf`, { type: "application/pdf" });
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

export async function downloadQuotePdf(quote) {
  saveFile(await fetchQuotePdf(quote));
}

/** True where the browser can hand a PDF to WhatsApp, email etc. (mostly phones). */
export function canShareFiles() {
  if (typeof navigator.canShare !== "function") return false;
  return navigator.canShare({ files: [new File([""], "quote.pdf", { type: "application/pdf" })] });
}

/**
 * Open the phone's share sheet with the quote PDF attached.
 * Returns "shared", "cancelled", or "downloaded" when the browser refuses to share
 * (some, notably iOS Safari, won't share after a slow network fetch).
 */
export async function shareQuotePdf(quote, text) {
  const file = await fetchQuotePdf(quote);
  try {
    await navigator.share({ files: [file], title: `Quotation ${quote.reference_number}`, text });
    return "shared";
  } catch (error) {
    if (error.name === "AbortError") return "cancelled";
    saveFile(file);
    return "downloaded";
  }
}
