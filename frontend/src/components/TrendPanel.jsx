import { useEffect, useState } from "react";
import { api } from "../services/api.js";
import PriceTrend from "./PriceTrend.jsx";

/** Loads one catalogue item's price and cost history the first time it is opened. */
export default function TrendPanel({ kind, id, unit }) {
  const [history, setHistory] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    const load = kind === "size" ? api.sizeHistory(id) : api.accessoryHistory(id);
    load.then((data) => !cancelled && setHistory(data)).catch((err) => !cancelled && setError(err.message));
    return () => {
      cancelled = true;
    };
  }, [kind, id]);

  return (
    <div className="trend-panel">
      {error ? (
        <div className="alert alert-error">{error}</div>
      ) : history === null ? (
        <p className="muted small">Loading history…</p>
      ) : (
        <PriceTrend history={history} unit={unit} />
      )}
    </div>
  );
}
