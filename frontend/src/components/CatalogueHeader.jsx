import { NavLink } from "react-router-dom";

/** Title, page action and the Cables / Accessories tabs shared by both catalogue pages. */
export default function CatalogueHeader({ action }) {
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Catalogue</h1>
          <div className="page-sub">Your prices, what the stock cost you, and the margin between them.</div>
        </div>
        {action}
      </div>
      <nav className="tabs" aria-label="Catalogue sections">
        <NavLink to="/catalogue" end className="tab">Cables</NavLink>
        <NavLink to="/catalogue/accessories" className="tab">Accessories</NavLink>
        <NavLink to="/catalogue/purchases" className="tab">Purchases</NavLink>
      </nav>
    </>
  );
}
