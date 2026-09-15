import { toNumber } from "../services/format.js";

/**
 * A series reduced to its shape: no axes, no labels, just the direction of travel.
 * The figure itself is written beside it — this only has to answer "which way, and how sharply?".
 */
export default function Sparkline({ points, colour = "var(--primary)", width = 76, height = 24, label }) {
  const values = points.map((point) => toNumber(point.value));
  if (!values.length) return null;

  const pad = 3;
  const [lowest, highest] = [Math.min(...values), Math.max(...values)];
  const span = highest - lowest || 1;
  const x = (index) => pad + (index / Math.max(values.length - 1, 1)) * (width - pad * 2);
  const y = (value) => height - pad - ((value - lowest) / span) * (height - pad * 2);

  return (
    <svg className="sparkline" viewBox={`0 0 ${width} ${height}`} width={width} height={height} role="img" aria-label={label}>
      {values.length === 1 ? (
        <circle cx={width / 2} cy={height / 2} r="2.5" fill={colour} />
      ) : (
        <>
          <polyline points={values.map((value, index) => `${x(index).toFixed(1)},${y(value).toFixed(1)}`).join(" ")}
            fill="none" stroke={colour} strokeWidth="1.6" strokeLinejoin="round" strokeLinecap="round" />
          <circle cx={x(values.length - 1)} cy={y(values[values.length - 1])} r="2.6" fill={colour} />
        </>
      )}
    </svg>
  );
}
