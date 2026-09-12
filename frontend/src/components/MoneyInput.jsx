import { useLayoutEffect, useRef, useState } from "react";
import { formatNaira } from "../services/format.js";

/**
 * Naira amount input: shows "₦76,500.00" at rest and the plain number while focused.
 * `value` is a plain numeric string; onChange receives the cleaned string as the user types.
 */
export default function MoneyInput({ value, onChange, onFocus, onBlur, ...props }) {
  const [editing, setEditing] = useState(false);
  const inputRef = useRef(null);
  const display = editing || value === "" ? value : `₦${formatNaira(value)}`;

  // Swapping the formatted text for the plain number resets the cursor to the end, which would make typed
  // digits append to the old amount (2500 -> "25002600"). Select it all instead, so typing replaces it.
  useLayoutEffect(() => {
    if (editing) inputRef.current?.select();
  }, [editing]);

  return (
    <input
      {...props}
      ref={inputRef}
      type="text"
      inputMode="decimal"
      autoComplete="off"
      value={display}
      onFocus={(event) => {
        setEditing(true);
        onFocus?.(event);
      }}
      onBlur={(event) => {
        setEditing(false);
        onBlur?.(event);
      }}
      onChange={(event) => onChange(event.target.value.replace(/[^\d.]/g, ""))}
    />
  );
}
