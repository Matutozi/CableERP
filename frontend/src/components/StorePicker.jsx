import { useEffect, useState } from "react";
import { api } from "../services/api.js";

/**
 * Which branch the signed-in member is working in.
 *
 * Hidden entirely below two branches — a single-branch business should never see a control with one
 * option in it. Changing branch reloads, because every list on the page is scoped server-side and a
 * partial refresh would leave some of them showing the old branch.
 */
export default function StorePicker() {
  const [state, setState] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api
      .currentStore()
      .then(setState)
      .catch(() => setState(null));
  }, []);

  if (!state?.selectable) return null;

  async function choose(value) {
    setBusy(true);
    try {
      await api.setCurrentStore(value === "all" ? null : value);
      window.location.reload();
    } catch {
      setBusy(false);
    }
  }

  return (
    <label className="store-picker">
      <span className="sr-only">Branch</span>
      <select
        value={state.current?.id ?? "all"}
        disabled={busy}
        onChange={(event) => choose(event.target.value)}
      >
        <option value="all">All branches</option>
        {state.available.map((store) => (
          <option key={store.id} value={store.id}>
            {store.name}
          </option>
        ))}
      </select>
    </label>
  );
}
