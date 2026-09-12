import { useNavigate } from "react-router-dom";
import { formatDate, formatNaira } from "../services/format.js";

export function StatusBadge({ status }) {
  return <span className={`badge badge-${status}`}>{status === "sent" ? "Sent" : "Draft"}</span>;
}

/** Quotes as a table on wide screens and as tappable cards on phones. A quote opens on its preview. */
export default function QuoteTable({ quotes }) {
  const navigate = useNavigate();
  const open = (quote) => navigate(`/quotes/${quote.id}/preview`);

  return (
    <>
      <table className="data-table desktop-only">
        <thead>
          <tr>
            <th>Reference</th>
            <th>Customer</th>
            <th>Date</th>
            <th>Status</th>
            <th className="num">Amount</th>
          </tr>
        </thead>
        <tbody>
          {quotes.map((quote) => (
            <tr key={quote.id} tabIndex={0} onClick={() => open(quote)} onKeyDown={(event) => event.key === "Enter" && open(quote)}>
              <td className="strong tabular">{quote.reference_number}</td>
              <td>{quote.customer_name}</td>
              <td className="dim">{formatDate(quote.date)}</td>
              <td><StatusBadge status={quote.status} /></td>
              <td className="num strong">₦{formatNaira(quote.grand_total)}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <div className="quote-cards mobile-only">
        {quotes.map((quote) => (
          <button key={quote.id} type="button" className="quote-card" onClick={() => open(quote)}>
            <div className="quote-card-top">
              <span className="quote-card-customer">{quote.customer_name}</span>
              <StatusBadge status={quote.status} />
            </div>
            <div className="quote-card-bottom">
              <span className="quote-card-meta">{quote.reference_number}, {formatDate(quote.date)}</span>
              <span className="quote-card-amount">₦{formatNaira(quote.grand_total)}</span>
            </div>
          </button>
        ))}
      </div>
    </>
  );
}
