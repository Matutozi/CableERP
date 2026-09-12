import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import QuoteTable from "../components/QuoteTable.jsx";
import { api } from "../services/api.js";

export default function QuoteList() {
  const [search, setSearch] = useState("");
  const [quotes, setQuotes] = useState(null);
  const [count, setCount] = useState(0);
  const [nextPage, setNextPage] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  // Searching and paging happen on the server, so a long history stays fast.
  useEffect(() => {
    let cancelled = false;
    const timer = setTimeout(() => {
      api.listQuotes({ search })
        .then((page) => {
          if (cancelled) return;
          setQuotes(page.results);
          setCount(page.count);
          setNextPage(page.next ? 2 : null);
        })
        .catch((err) => !cancelled && setError(err.message));
    }, search ? 300 : 0);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [search]);

  async function loadMore() {
    setBusy(true);
    setError("");
    try {
      const page = await api.listQuotes({ search, page: nextPage });
      setQuotes((current) => [...current, ...page.results]);
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
          <h1>Quotes</h1>
          <div className="page-sub">
            {quotes === null ? "\u00a0" : `${count} ${count === 1 ? "quote" : "quotes"}${search ? " found" : ""}`}
          </div>
        </div>
        <Link className="btn btn-primary" to="/quotes/new">New quote</Link>
      </div>

      {error && <div className="alert alert-error">{error}</div>}

      {(search || (quotes?.length ?? 0) > 0) && (
        <input className="search" type="search" placeholder="Search by customer or reference" value={search}
          onChange={(event) => setSearch(event.target.value)} aria-label="Search quotes" />
      )}

      {quotes === null ? (
        !error && <p className="muted">Loading…</p>
      ) : quotes.length === 0 ? (
        <div className="empty">{search ? "No quotes match your search." : "No quotes yet."}</div>
      ) : (
        <>
          <QuoteTable quotes={quotes} />
          {nextPage && (
            <div className="load-more">
              <button type="button" className="btn btn-secondary" onClick={loadMore} disabled={busy}>
                {busy ? "Loading…" : `Load more (${count - quotes.length} left)`}
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
