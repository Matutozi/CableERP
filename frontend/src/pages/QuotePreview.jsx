import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import Icon from "../components/Icon.jsx";
import { api } from "../services/api.js";
import { formatDate, formatNaira, formatQty, toNumber, unitLabel } from "../services/format.js";
import { canShareFiles, downloadQuotePdf, shareQuotePdf } from "../services/pdf.js";

const nairaOrDash = (value) => (toNumber(value) ? `₦${formatNaira(value)}` : "–");

function shareMessage(quote, business) {
  return `Hello, please find attached quotation ${quote.reference_number} from ${business.business_name}. `
    + `Grand total: ₦${formatNaira(quote.grand_total)}.`;
}

/** An on-screen copy of the PDF, with the ways to send it. */
export default function QuotePreview() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [quote, setQuote] = useState(null);
  const [business, setBusiness] = useState(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  useEffect(() => {
    Promise.all([api.getQuote(id), api.getProfile()])
      .then(([quoteData, profile]) => {
        setQuote(quoteData);
        setBusiness(profile);
      })
      .catch((err) => setError(err.message));
  }, [id]);

  async function run(action, task) {
    setBusy(action);
    setError("");
    setNotice("");
    try {
      await task();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy("");
    }
  }

  const handleDownload = () =>
    run("download", async () => {
      await downloadQuotePdf(quote);
      setNotice(`Downloaded ${quote.reference_number}.pdf.`);
    });

  // A waybill copies the quote's lines as they stand, so it is made from this saved version.
  const handleWaybill = () =>
    run("waybill", async () => {
      const waybill = await api.createWaybill(quote.id);
      navigate(`/quotes/waybills/${waybill.id}`);
    });

  function handleWhatsApp() {
    if (!canShareFiles()) {
      // Desktop browsers can't hand a file to WhatsApp: open a chat with the message, and download the PDF to attach.
      window.open(`https://wa.me/?text=${encodeURIComponent(shareMessage(quote, business))}`, "_blank", "noopener");
      run("whatsapp", async () => {
        await downloadQuotePdf(quote);
        setNotice("WhatsApp opened in a new tab and the PDF was downloaded. Attach it to the chat.");
      });
      return;
    }
    run("whatsapp", async () => {
      const outcome = await shareQuotePdf(quote, shareMessage(quote, business));
      if (outcome === "shared") {
        if (quote.status !== "sent") setQuote(await api.patchQuote(quote.id, { status: "sent" }));
        setNotice("Sent. The quote is now marked as sent.");
      } else if (outcome === "downloaded") {
        setNotice("This browser couldn't open the share menu, so the PDF was downloaded. Attach it in WhatsApp.");
      }
    });
  }

  if (!quote || !business) {
    return <div className="page">{error ? <div className="alert alert-error">{error}</div> : <p className="muted">Loading…</p>}</div>;
  }

  const phones = business.phone_numbers.split(",").map((phone) => phone.trim()).filter(Boolean);
  // Payment details are frozen onto the quote when it is created; quotes from before that fall back to the profile.
  const payment = {
    bank: quote.payment_bank_name || business.bank_name,
    accountNumber: quote.payment_account_number || business.account_number,
    accountName: quote.payment_account_name || business.account_name || business.business_name,
  };
  const terms = [
    ["NB", business.disclaimer],
    ["Payment terms", business.payment_terms],
    ["Quotation validity", business.quote_validity],
    ["Notes", quote.notes],
  ].filter(([, text]) => text);

  return (
    <div className="preview-page">
      <div className="preview-toolbar">
        <Link to={`/quotes/${quote.id}`} className="back-link"><Icon name="back" size={14} strokeWidth={1.6} />Back to quote</Link>
        <div className="toolbar-actions">
          <button type="button" className="btn btn-secondary" onClick={handleWaybill} disabled={!!busy}>
            {busy === "waybill" ? "Creating…" : "Create waybill"}
          </button>
          <button type="button" className="btn btn-secondary" onClick={handleDownload} disabled={!!busy}>
            {busy === "download" ? "Preparing…" : "Download"}
          </button>
          <button type="button" className="btn btn-whatsapp" onClick={handleWhatsApp} disabled={!!busy}>
            {busy === "whatsapp" ? "Preparing…" : "Send on WhatsApp"}
          </button>
        </div>
      </div>

      {error && <div className="alert alert-error">{error}</div>}
      {notice && <div className="alert alert-success">{notice}</div>}

      <article className="doc">
        <header className="doc-head">
          <div className="doc-business">
            {business.logo && <img src={business.logo} alt="" className="doc-logo" />}
            <div>
              <div className="doc-business-name">{business.business_name}</div>
              <div className="doc-small">
                {business.address && <>{business.address}<br /></>}
                {phones.length > 0 && <>{phones.join(", ")}<br /></>}
                {business.email}
              </div>
            </div>
          </div>
          <div className="doc-title">
            {business.brand_logo && <img src={business.brand_logo} alt="" className="doc-brand-logo" />}
            <div className="doc-title-word">QUOTATION</div>
            <div className="doc-small num">{quote.reference_number}<br />{formatDate(quote.date)}</div>
          </div>
        </header>

        <div className="doc-parties">
          <div><div className="doc-label">Quotation for</div><div className="doc-value">{quote.customer_name}</div></div>
          <div>
            <div className="doc-label">Prepared by</div>
            <div className="doc-value">{quote.staff_name}{quote.staff_phone && <span className="doc-small"> · {quote.staff_phone}</span>}</div>
          </div>
          {quote.product_manufacturer && (
            <div><div className="doc-label">Product / Manufacturer</div><div className="doc-value">{quote.product_manufacturer}</div></div>
          )}
        </div>

        <div className="table-scroll">
          <table className="doc-table">
            <thead>
              <tr>
                <th className="sn">S/N</th>
                <th>Description</th>
                <th className="num">Price (₦)</th>
                <th className="num">Qty</th>
                <th className="num">Amount (₦)</th>
              </tr>
            </thead>
            {quote.line_items.map((item, index) => (
              <tbody key={item.id}>
                <tr className="doc-main">
                  <td className="sn">{index + 1}</td>
                  <td>{item.description}</td>
                  <td className="num">{formatNaira(item.unit_price)}</td>
                  <td className="num">{formatQty(item.total_quantity)} {unitLabel(item.unit, item.total_quantity)}</td>
                  <td className="num">{formatNaira(item.amount)}</td>
                </tr>
                {item.colours.filter((entry) => entry.colour).map((entry) => (
                  <tr key={entry.id} className="doc-colour">
                    <td />
                    <td>{entry.colour}</td>
                    <td />
                    <td className="num">{formatQty(entry.quantity)}</td>
                    <td />
                  </tr>
                ))}
              </tbody>
            ))}
          </table>
        </div>

        <div className="doc-totals">
          <div><span>Subtotal</span><span>₦{formatNaira(quote.subtotal)}</span></div>
          <div><span>VAT{toNumber(quote.vat_percentage) ? ` (${formatQty(quote.vat_percentage)}%)` : ""}</span><span>{nairaOrDash(quote.vat_amount)}</span></div>
          <div><span>Transport</span><span>{nairaOrDash(quote.transport_cost)}</span></div>
          <div className="doc-grand"><span>Grand total</span><span>₦{formatNaira(quote.grand_total)}</span></div>
        </div>

        {(payment.bank || payment.accountNumber || terms.length > 0) && (
          <footer className="doc-foot">
            {(payment.bank || payment.accountNumber) && (
              <div>
                <div className="doc-foot-title">Payment</div>
                <div className="doc-small">
                  {[payment.bank, payment.accountNumber].filter(Boolean).join(", ")}<br />
                  {payment.accountName}
                </div>
              </div>
            )}
            {terms.length > 0 && (
              <div className="doc-terms">
                <div className="doc-foot-title">Terms</div>
                {terms.map(([label, text]) => (
                  <p key={label} className="doc-small"><strong>{label}:</strong> {text}</p>
                ))}
              </div>
            )}
          </footer>
        )}
      </article>
    </div>
  );
}
