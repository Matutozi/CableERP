import { formatCost, formatPercent } from "../services/format.js";

/**
 * What a catalogue item cost at its last delivery, and the margin the current price leaves.
 * Items with no purchase recorded say so rather than showing a margin of 100%.
 */
export default function CostNote({ row, unit }) {
  if (row.last_unit_cost === null || row.last_unit_cost === undefined) {
    return <span className="cost-note none">No purchase recorded</span>;
  }
  const margin = Number(row.margin_percentage);
  return (
    <span className="cost-note">
      Cost ₦{formatCost(row.last_unit_cost)}{unit ? ` / ${unit}` : ""}
      <span className={margin < 0 ? "margin-chip loss" : "margin-chip"}>{formatPercent(row.margin_percentage)}</span>
    </span>
  );
}
