import { NavLink } from "react-router-dom";

/** Title, page action and the Cables / Accessories tabs shared by both catalogue pages. */
export default function CatalogueHeader({ action }) {
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Catalogue</h1>
          <div className="page-sub">Your prices for cables and accessories. Tap a price to edit it.</div>
        </div>
        {action}
      </div>
      <nav className="tabs" aria-label="Catalogue sections">
        <NavLink to="/catalogue" end className="tab">Cables</NavLink>
        <NavLink to="/catalogue/accessories" className="tab">Accessories</NavLink>
      </nav>
    </>
  );
}
