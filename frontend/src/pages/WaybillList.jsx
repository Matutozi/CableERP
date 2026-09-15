import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import DocumentTabs from "../components/DocumentTabs.jsx";
import { api } from "../services/api.js";
import { formatDate } from "../services/format.js";

export default function WaybillList() {
  const [waybills, setWaybills] = useState(null);
  const [count, setCount] = useState(0);
  const [nextPage, setNextPage] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api.listWaybills()
      .then((page) => {
        setWaybills(page.results);
        setCount(page.count);
        setNextPage(page.next ? 2 : null);
      })
      .catch((err) => setError(err.message));
  }, []);

  async function loadMore() {
    setBusy(true);
    setError("");
    try {
      const page = await api.listWaybills({ page: nextPage });
      setWaybills((current) => [...current, ...page.results]);
      setNextPage(page.next ? nextPage + 1 : null);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Waybills</h1>
          <div className="page-sub">{waybills === null ? " " : `${count} ${count === 1 ? "waybill" : "waybills"}`}</div>
        </div>
      </div>
      <DocumentTabs />

      {error && <div className="alert alert-error">{error}</div>}

      {waybills === null ? (
        !error && <p className="muted">Loading…</p>
      ) : waybills.length === 0 ? (
        <div className="empty">
          No waybills yet. Open a quote's preview and tap <strong>Create waybill</strong> when the goods go out.
        </div>
      ) : (
        <>
          <div className="panel flush waybill-rows">
            {waybills.map((waybill) => (
              <Link key={waybill.id} to={`/quotes/waybills/${waybill.id}`} className="waybill-row">
                <span className="waybill-main">
                  <span className="waybill-customer">{waybill.customer_name}</span>
                  <span className="waybill-sub">
                    {formatDate(waybill.date)} · {waybill.item_count} {waybill.item_count === 1 ? "item" : "items"}
                    {waybill.quote_reference && ` · from ${waybill.quote_reference}`}
                  </span>
                </span>
                <span className="waybill-ref tabular">{waybill.reference_number}</span>
              </Link>
            ))}
          </div>
          {nextPage && (
            <div className="load-more">
              <button type="button" className="btn btn-secondary" onClick={loadMore} disabled={busy}>
                {busy ? "Loading…" : `Load more (${count - waybills.length} left)`}
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
