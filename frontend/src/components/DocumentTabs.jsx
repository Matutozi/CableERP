import { NavLink } from "react-router-dom";

/** Quotes and the waybills made from them, as two tabs of the same section. */
export default function DocumentTabs() {
  return (
    <nav className="tabs" aria-label="Documents">
      <NavLink to="/quotes" end className="tab">Quotes</NavLink>
      <NavLink to="/quotes/waybills" className="tab">Waybills</NavLink>
    </nav>
  );
}
