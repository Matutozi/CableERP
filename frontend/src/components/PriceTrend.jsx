import { formatDate, formatNaira, toNumber, unitLabel } from "../services/format.js";

const W = 320;
const H = 116;
const PAD = { top: 10, right: 8, bottom: 20, left: 8 };

/** Percentage move from the first point to the last, or null when there is nothing to compare. */
function drift(points) {
  if (points.length < 2) return null;
  const [first] = points;
  const last = points[points.length - 1];
  if (!first.value) return null;
  return ((last.value - first.value) / first.value) * 100;
}

function Delta({ change }) {
  if (change === null) return <span className="trend-delta flat">no change yet</span>;
  const rounded = Math.round(change * 10) / 10;
  if (rounded === 0) return <span className="trend-delta flat">unchanged</span>;
  return (
    <span className={rounded > 0 ? "trend-delta up" : "trend-delta down"}>
      {rounded > 0 ? "▲" : "▼"} {Math.abs(rounded)}%
    </span>
  );
}

/**
 * What an item has sold for against what it has cost, over time.
 *
 * Two independent series: the seller moves the price, the market moves the cost. Drawn on one
 * scale so the gap between them — the margin — is the thing you actually see widen or close.
 */
export default function PriceTrend({ history, unit }) {
  const price = history.price.map((point) => ({ ...point, value: toNumber(point.value) }));
  const cost = history.cost.map((point) => ({ ...point, value: toNumber(point.value) }));
  const all = [...price, ...cost];

  if (!all.length) return <p className="muted small">Nothing recorded for this item yet.</p>;

  const times = all.map((point) => Date.parse(point.date));
  const values = all.map((point) => point.value);
  const [minT, maxT] = [Math.min(...times), Math.max(...times)];
  const [lowest, highest] = [Math.min(...values), Math.max(...values)];
  // A flat series would collapse to a zero-height scale, so give it room to sit in the middle.
  const pad = highest === lowest ? Math.max(highest * 0.1, 1) : (highest - lowest) * 0.15;
  const [minV, maxV] = [lowest - pad, highest + pad];

  const x = (point) => PAD.left + ((Date.parse(point.date) - minT) / (maxT - minT || 1)) * (W - PAD.left - PAD.right);
  const y = (point) => H - PAD.bottom - ((point.value - minV) / (maxV - minV || 1)) * (H - PAD.top - PAD.bottom);
  const path = (points) => points.map((point) => `${x(point).toFixed(1)},${y(point).toFixed(1)}`).join(" ");

  const series = [
    { key: "price", label: "Your price", points: price, colour: "var(--primary)", dash: "" },
    { key: "cost", label: "What it cost", points: cost, colour: "#b45309", dash: "4 3" },
  ].filter((entry) => entry.points.length);

  const latest = (points) => points[points.length - 1];

  return (
    <div className="trend">
      <div className="trend-legend">
        {series.map((entry) => (
          <span key={entry.key} className="trend-key">
            <span className="trend-swatch" style={{ background: entry.colour, opacity: entry.dash ? 0.8 : 1 }} />
            {entry.label}
            <strong>₦{formatNaira(latest(entry.points).value)}</strong>
            {unit && <span className="trend-unit">/{unit}</span>}
            <Delta change={drift(entry.points)} />
          </span>
        ))}
      </div>

      <svg className="trend-chart" viewBox={`0 0 ${W} ${H}`} role="img"
        aria-label={series.map((entry) => `${entry.label}: ${entry.points.length} points, latest ₦${formatNaira(latest(entry.points).value)}`).join(". ")}>
        <line x1={PAD.left} y1={H - PAD.bottom} x2={W - PAD.right} y2={H - PAD.bottom} stroke="var(--border)" strokeWidth="1" />
        {series.map((entry) => (
          <g key={entry.key}>
            {entry.points.length > 1 && (
              <polyline points={path(entry.points)} fill="none" stroke={entry.colour} strokeWidth="1.8"
                strokeDasharray={entry.dash} strokeLinejoin="round" strokeLinecap="round" />
            )}
            {entry.points.map((point, index) => (
              <circle key={`${point.date}-${index}`} cx={x(point)} cy={y(point)} r={index === entry.points.length - 1 ? 3.5 : 2.5}
                fill={entry.colour} stroke="var(--surface)" strokeWidth="1" />
            ))}
          </g>
        ))}
        <text x={PAD.left} y={H - 6} fill="var(--muted)" fontSize="9">{formatDate(new Date(minT).toISOString())}</text>
        <text x={W - PAD.right} y={H - 6} fill="var(--muted)" fontSize="9" textAnchor="end">
          {formatDate(new Date(maxT).toISOString())}
        </text>
      </svg>

      <ol className="trend-log">
        {[...all]
          .map((point, index) => ({ ...point, kind: index < price.length ? "price" : "cost" }))
          .sort((a, b) => Date.parse(b.date) - Date.parse(a.date))
          .slice(0, 6)
          .map((point, index) => (
            <li key={`${point.kind}-${point.date}-${index}`}>
              <span className="trend-log-date">{formatDate(point.date)}</span>
              <span className="trend-log-what">
                {point.kind === "price" ? "Priced at" : "Bought"}
                {point.kind === "cost" && point.quantity
                  ? ` ${Number(point.quantity)} ${unitLabel(unit, Number(point.quantity))} at`
                  : ""}
                {point.kind === "cost" && point.supplier ? ` from ${point.supplier},` : ""}
              </span>
              <span className="trend-log-value">₦{formatNaira(point.value)}</span>
            </li>
          ))}
      </ol>
    </div>
  );
}
