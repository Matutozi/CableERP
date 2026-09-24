import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import Icon from "../components/Icon.jsx";
import { api } from "../services/api.js";
import { formatDate, formatQty, unitLabel } from "../services/format.js";
import { canShareFiles, downloadWaybillPdf, shareWaybillPdf } from "../services/pdf.js";

function shareMessage(waybill, business) {
  return (
    `Waybill ${waybill.reference_number} from ${business.business_name} ` +
    `for ${waybill.customer_name}, dated ${formatDate(waybill.date)}.`
  );
}

/**
 * An on-screen copy of the waybill PDF, with the ways to send it.
 *
 * Mirrors QuotePreview deliberately, with one difference that is the whole point of the document:
 * **no prices anywhere.** A waybill travels with the goods and is read by a driver, a gateman and
 * whoever signs for the delivery, none of whom should learn what the customer paid.
 */
export default function WaybillPreview() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [waybill, setWaybill] = useState(null);
  const [business, setBusiness] = useState(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  useEffect(() => {
    Promise.all([api.getWaybill(id), api.getProfile()])
      .then(([waybillData, profile]) => {
        setWaybill(waybillData);
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

  if (error && !waybill) return <div className="page alert alert-error">{error}</div>;
  if (!waybill || !business) return <div className="page">Loading…</div>;

  const phones = business.phone_numbers ? business.phone_numbers.split(",").map((p) => p.trim()) : [];
  const colours = waybill.colour_columns ?? [];

  return (
    <div className="page">
      <div className="page-head">
        <Link to="/quotes/waybills" className="btn btn-ghost">
          <Icon name="arrow-left" size={16} /> Waybills
        </Link>
        <div className="page-head-actions">
          <Link to={`/quotes/waybills/${waybill.id}`} className="btn btn-secondary">
            Edit
          </Link>
          <button
            type="button"
            className="btn btn-secondary"
            disabled={busy !== ""}
            onClick={() => run("download", () => downloadWaybillPdf(waybill))}
          >
            {busy === "download" ? "Preparing…" : "Download PDF"}
          </button>
          {canShareFiles() && (
            <button
              type="button"
              className="btn btn-primary"
              disabled={busy !== ""}
              onClick={() =>
                run("share", async () => {
                  const sent = await shareWaybillPdf(waybill, shareMessage(waybill, business));
                  if (!sent) setNotice("Sharing was cancelled.");
                })
              }
            >
              {busy === "share" ? "Preparing…" : "Send"}
            </button>
          )}
        </div>
      </div>

      {error && <div className="alert alert-error">{error}</div>}
      {notice && <div className="alert">{notice}</div>}

      <article className="doc doc-waybill">
        <header className="doc-head">
          <div className="doc-identity">
            {business.logo && <img src={business.logo} alt="" className="doc-logo" />}
            <div>
              <div className="doc-business">{business.business_name}</div>
              <div className="doc-small">
                {business.address}
                <br />
                {phones.length > 0 && (
                  <>
                    {phones.join(", ")}
                    <br />
                  </>
                )}
                {business.email}
              </div>
            </div>
          </div>
          <div className="doc-title">
            {business.brand_logo && <img src={business.brand_logo} alt="" className="doc-brand-logo" />}
            <div className="doc-title-word">WAYBILL</div>
            <div className="doc-small num">
              {waybill.reference_number}
              <br />
              {formatDate(waybill.date)}
            </div>
          </div>
        </header>

        <div className="doc-parties">
          <div>
            <div className="doc-label">M/S</div>
            <div className="doc-value">{waybill.customer_name}</div>
          </div>
          {waybill.invoice_number && (
            <div>
              <div className="doc-label">Invoice No</div>
              <div className="doc-value">{waybill.invoice_number}</div>
            </div>
          )}
          {waybill.branch && (
            <div>
              <div className="doc-label">Branch</div>
              <div className="doc-value">{waybill.branch}</div>
            </div>
          )}
          {waybill.vehicle_number && (
            <div>
              <div className="doc-label">Vehicle No</div>
              <div className="doc-value">{waybill.vehicle_number}</div>
            </div>
          )}
          {waybill.product_manufacturer && (
            <div>
              <div className="doc-label">Product / Manufacturer</div>
              <div className="doc-value">{waybill.product_manufacturer}</div>
            </div>
          )}
        </div>

        <div className="table-scroll">
          <table className="doc-table">
            <thead>
              <tr>
                <th className="sn">S/N</th>
                <th className="num">Qty</th>
                <th>Model</th>
                <th>Description</th>
                {colours.map((colour) => (
                  <th key={colour} className="num">
                    {colour}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {waybill.items.map((item, index) => {
                const byColour = Object.fromEntries(
                  item.colours.map((entry) => [entry.colour, entry.quantity]),
                );
                return (
                  <tr key={item.id} className="doc-main">
                    <td className="sn">{index + 1}</td>
                    <td className="num">
                      {formatQty(item.total_quantity)} {unitLabel(item.unit, item.total_quantity)}
                    </td>
                    <td>{item.model_label}</td>
                    <td>{item.description}</td>
                    {colours.map((colour) => (
                      <td key={colour} className="num">
                        {byColour[colour] ? formatQty(byColour[colour]) : ""}
                      </td>
                    ))}
                  </tr>
                );
              })}
            </tbody>
            {waybill.totals?.length > 0 && (
              <tfoot>
                <tr className="doc-grand">
                  <td />
                  <td className="num">Total</td>
                  <td colSpan={2} />
                  {waybill.totals.map((total, index) => (
                    <td key={colours[index] ?? index} className="num">
                      {formatQty(total)}
                    </td>
                  ))}
                </tr>
              </tfoot>
            )}
          </table>
        </div>

        {waybill.notes && <p className="doc-notes">{waybill.notes}</p>}

        {/* The signature block is the point of the paper: proof the goods arrived. */}
        <div className="doc-signatures">
          <div>
            <div className="doc-sign-line" />
            <div className="doc-label">Driver</div>
          </div>
          <div>
            <div className="doc-sign-line" />
            <div className="doc-label">Received by (name &amp; signature)</div>
          </div>
          <div>
            <div className="doc-sign-line" />
            <div className="doc-label">Date</div>
          </div>
        </div>
      </article>

      <button type="button" className="btn btn-ghost" onClick={() => navigate(-1)}>
        Back
      </button>
    </div>
  );
}
