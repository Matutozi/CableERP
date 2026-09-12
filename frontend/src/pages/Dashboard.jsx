import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import QuoteTable from "../components/QuoteTable.jsx";
import { useAuth } from "../context/AuthContext.jsx";
import { api } from "../services/api.js";

function greeting() {
  const hour = new Date().getHours();
  if (hour < 12) return "Good morning";
  return hour < 17 ? "Good afternoon" : "Good evening";
}

export default function Dashboard() {
  const { user } = useAuth();
  const [quotes, setQuotes] = useState(null);
  const [profile, setProfile] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([api.listQuotes({ pageSize: 5 }), api.getProfile()])
      .then(([page, businessProfile]) => {
        setQuotes(page.results);
        setProfile(businessProfile);
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
