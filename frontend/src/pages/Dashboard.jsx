import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import PriceTrend from "../components/PriceTrend.jsx";
import QuoteTable from "../components/QuoteTable.jsx";
import Sparkline from "../components/Sparkline.jsx";
import { useAuth } from "../context/AuthContext.jsx";
import { api } from "../services/api.js";
import { formatCost, formatDate, formatPercent, toNumber, unitLabel } from "../services/format.js";

/** Percentage move across a series, or null when there is only one point to go on. */
function move(points) {
  if (points.length < 2) return null;
  const first = toNumber(points[0].value);
  if (!first) return null;
  return ((toNumber(points[points.length - 1].value) - first) / first) * 100;
}

function Movement({ item }) {
  const [open, setOpen] = useState(false);
  const change = move(item.history.cost);
  const margin = item.margin_percentage === null ? null : Number(item.margin_percentage);

  return (
    <div className={open ? "movement open" : "movement"}>
      <button type="button" className="movement-row" aria-expanded={open} onClick={() => setOpen(!open)}>
        <span className="movement-main">
          <span className="movement-name">{item.name}</span>
          <span className="movement-sub">
            Cost ₦{formatCost(item.last_unit_cost)} / {unitLabel(item.unit, 1)}
            {margin !== null && (
              <span className={margin < 0 ? "margin-chip loss" : "margin-chip"}>{formatPercent(margin)}</span>
            )}
          </span>
        </span>
        <Sparkline points={item.history.cost} colour="#b45309" label={`Cost history for ${item.name}`} />
        <span className="movement-change">
          {change === null ? (
            <span className="trend-delta flat">first buy</span>
          ) : (
            // Cost going up is the bad direction, so it is the one shown in red.
            <span className={change > 0 ? "trend-delta up" : change < 0 ? "trend-delta down" : "trend-delta flat"}>
              {change > 0 ? "▲" : change < 0 ? "▼" : ""} {Math.abs(Math.round(change * 10) / 10)}%
            </span>
          )}
          <span className="movement-date">{formatDate(item.last_moved)}</span>
        </span>
      </button>
      {open && (
        <div className="trend-panel">
          <PriceTrend history={item.history} unit={item.unit} />
        </div>
      )}
    </div>
  );
}

function greeting() {
  const hour = new Date().getHours();
  if (hour < 12) return "Good morning";
  return hour < 17 ? "Good afternoon" : "Good evening";
}

export default function Dashboard() {
  const { user } = useAuth();
  const [quotes, setQuotes] = useState(null);
  const [profile, setProfile] = useState(null);
  const [movements, setMovements] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([api.listQuotes({ pageSize: 5 }), api.getProfile(), api.priceMovements()])
      .then(([page, businessProfile, moved]) => {
        setQuotes(page.results);
        setProfile(businessProfile);
        setMovements(moved);
      })
      .catch((err) => setError(err.message));
  }, []);

  const firstName = user.full_name?.split(" ")[0];
  const setupIncomplete = profile && (!profile.phone_numbers || !profile.bank_name || !profile.account_number);

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>{greeting()}{firstName ? `, ${firstName}` : ""}</h1>
          <div className="page-sub">{user.business_name}</div>
        </div>
        <Link to="/quotes/new" className="btn btn-primary">New quote</Link>
      </div>

      {setupIncomplete && (
        <div className="alert alert-info">
          Add your phone numbers and bank details so they appear on your quotes. <Link to="/settings">Finish setup →</Link>
        </div>
      )}
      {error && <div className="alert alert-error">{error}</div>}

      {movements !== null && movements.length > 0 && (
        <>
          <div className="section-head">
            <h2>Price movements</h2>
            <Link to="/catalogue/purchases" className="small">Record a purchase</Link>
          </div>
          <div className="panel flush movements">
            {movements.map((item) => <Movement key={`${item.kind}-${item.id}`} item={item} />)}
          </div>
        </>
      )}

      <div className="section-head">
        <h2>Recent quotes</h2>
        {quotes?.length > 0 && <Link to="/quotes" className="small">View all</Link>}
      </div>
      {quotes === null ? (
        !error && <p className="muted">Loading…</p>
      ) : quotes.length === 0 ? (
        <div className="empty">No quotes yet. Your quotes will show up here once you create one.</div>
      ) : (
        <QuoteTable quotes={quotes} />
      )}
    </div>
  );
}
