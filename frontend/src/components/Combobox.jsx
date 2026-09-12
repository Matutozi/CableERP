import { useEffect, useId, useRef, useState } from "react";
import Icon from "./Icon.jsx";

/**
 * A picker that opens its full list on tap and still accepts anything typed — the catalogue is a
 * starting point, not a limit. Used for cable types, sizes and accessories on a quote line.
 */
export default function Combobox({ value, options, placeholder, ariaLabel, autoFocus, onChange }) {
  const [open, setOpen] = useState(false);
  const [highlighted, setHighlighted] = useState(-1);
  const wrapper = useRef(null);
  const listId = useId();

  const typed = value.trim().toLowerCase();
  const exact = options.some((option) => option.value.toLowerCase() === typed);
  // Once the text matches an option, show everything again so another one can be picked.
  const visible = !typed || exact ? options : options.filter((option) => option.value.toLowerCase().includes(typed));

  useEffect(() => {
    if (!open) return undefined;
    const onPointerDown = (event) => {
      if (!wrapper.current?.contains(event.target)) setOpen(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [open]);

  function choose(option) {
    onChange(option.value);
    setOpen(false);
    setHighlighted(-1);
  }

  function onKeyDown(event) {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (!open) return setOpen(true);
      const step = event.key === "ArrowDown" ? 1 : -1;
      setHighlighted((current) => (current + step + visible.length) % Math.max(visible.length, 1));
    } else if (event.key === "Enter" && open && highlighted >= 0 && visible[highlighted]) {
      event.preventDefault();
      choose(visible[highlighted]);
    } else if (event.key === "Escape" && open) {
      event.preventDefault();
      setOpen(false);
    }
  }

  return (
    <div
      className="combobox"
      ref={wrapper}
      // Tabbing or moving to the next field closes the list, so it can never hang over the card below.
      onBlur={(event) => {
        if (!wrapper.current?.contains(event.relatedTarget)) setOpen(false);
      }}
    >
      <div className="combobox-field">
        <input
          type="text"
          role="combobox"
          aria-expanded={open}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-label={ariaLabel}
          autoComplete="off"
          placeholder={placeholder}
          value={value}
          autoFocus={autoFocus}
          onChange={(event) => {
            onChange(event.target.value);
            setOpen(true);
            setHighlighted(-1);
          }}
          onFocus={() => setOpen(true)}
          onKeyDown={onKeyDown}
        />
        <button
          type="button"
          className="combobox-toggle"
          tabIndex={-1}
          aria-label={open ? "Hide the list" : "Show the list"}
          onClick={() => setOpen((current) => !current)}
        >
          <Icon name="chevron" size={14} strokeWidth={1.8} />
        </button>
      </div>

      {open && (
        <ul className="combobox-list" id={listId} role="listbox">
          {visible.map((option, index) => (
            <li key={option.value}>
              <button
                type="button"
                role="option"
                aria-selected={option.value.toLowerCase() === typed}
                className={index === highlighted ? "combobox-option highlighted" : "combobox-option"}
                title={option.value}
                onMouseEnter={() => setHighlighted(index)}
                onMouseDown={(event) => event.preventDefault()} // keep focus so the blur doesn't close us first
                onClick={() => choose(option)}
              >
                <span className="combobox-name">{option.value}</span>
                {option.hint && <span className="combobox-hint">{option.hint}</span>}
              </button>
            </li>
          ))}
          {visible.length === 0 && (
            <li className="combobox-empty">Not in your catalogue — it will be quoted exactly as typed.</li>
          )}
        </ul>
      )}
    </div>
  );
}
