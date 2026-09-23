import { useState } from "react";
import { toNumber } from "../services/format.js";
import MoneyInput from "./MoneyInput.jsx";

/** A catalogue price edited in place: saves on blur or Enter, then shows a tick. */
export default function InlinePrice({ price, label, onSave }) {
  const [value, setValue] = useState(String(toNumber(price)));
  const [state, setState] = useState("idle"); // idle | saving | saved
  const [lastPrice, setLastPrice] = useState(price);

  // The catalogue price can change underneath this field: a save elsewhere, or a reload.
  // Resyncing during render rather than in an effect keeps it to a single render pass.
  if (lastPrice !== price) {
    setLastPrice(price);
    setValue(String(toNumber(price)));
  }

  async function commit() {
    if (value === "" || toNumber(value) === toNumber(price)) {
      setValue(String(toNumber(price)));
      return;
    }
    setState("saving");
    try {
      await onSave(toNumber(value).toFixed(2));
      setState("saved");
    } catch {
      // The caller shows the error; put the saved price back.
      setState("idle");
      setValue(String(toNumber(price)));
    }
  }

  return (
    <span className="inline-price">
      <MoneyInput
        className="inline-input"
        value={value}
        aria-label={label}
        onChange={(next) => {
          setValue(next);
          setState("idle");
        }}
        onBlur={commit}
        onKeyDown={(event) => event.key === "Enter" && event.currentTarget.blur()}
      />
      <span className={`save-state ${state}`} aria-live="polite">
        {state === "saved" ? "✓" : state === "saving" ? "…" : ""}
      </span>
    </span>
  );
}
