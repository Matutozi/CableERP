import { useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "../context/AuthContext.jsx";
import Icon from "./Icon.jsx";

const NAV = [
  { to: "/", label: "Dashboard", icon: "dashboard", end: true },
  { to: "/quotes", label: "Quotes", icon: "quotes" },
  { to: "/catalogue", label: "Catalogue", icon: "catalogue" },
  { to: "/settings", label: "Settings", icon: "settings" },
];

function initials(user) {
  const source = user.full_name || user.username || "";
  return source.split(/\s+/).filter(Boolean).slice(0, 2).map((word) => word[0].toUpperCase()).join("");
}

function screenTitle(pathname) {
  if (pathname === "/") return "Dashboard";
  if (pathname === "/quotes/new") return "New quote";
  if (pathname === "/quotes/waybills") return "Waybills";
  if (pathname.startsWith("/quotes/waybills/")) return "Waybill";
  if (pathname.endsWith("/preview")) return "Quote preview";
  if (pathname.startsWith("/quotes/")) return "Quote";
  if (pathname.startsWith("/quotes")) return "Quotes";
  if (pathname.startsWith("/catalogue")) return "Catalogue";
  if (pathname.startsWith("/settings")) return "Settings";
  return "CableERP";
}

function SidebarContent({ user, onNavigate, onLogout }) {
  return (
    <>
      <div className="sidebar-brand">
        <div className="sidebar-business">{user.business_name ?? "CableERP"}</div>
        <div className="sidebar-product">CableERP</div>
      </div>
      <nav className="sidebar-nav" aria-label="Main">
        {NAV.map((item) => (
          <NavLink key={item.to} to={item.to} end={item.end} className="nav-item" onClick={onNavigate}>
            <Icon name={item.icon} />
            <span>{item.label}</span>
          </NavLink>
        ))}
      </nav>
      <div className="sidebar-user">
        <span className="avatar">{initials(user)}</span>
        <div className="user-text">
          <div className="user-name">{user.full_name || user.username}</div>
          <div className="user-sub">@{user.username}</div>
        </div>
        <button type="button" className="icon-btn" onClick={onLogout} aria-label="Log out" title="Log out">
          <Icon name="logout" />
        </button>
      </div>
    </>
  );
}

export default function Layout() {
  const { user, logout } = useAuth();
  const { pathname } = useLocation();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const closeDrawer = () => setDrawerOpen(false);

  return (
    <div className="shell">
      <aside className="sidebar">
        <SidebarContent user={user} onLogout={logout} />
      </aside>

      <div className="main-col">
        <header className="mobile-header">
          <button type="button" className="hamburger" aria-label="Open menu" onClick={() => setDrawerOpen(true)}>
            <span />
            <span />
            <span />
          </button>
          <span className="mobile-title">{screenTitle(pathname)}</span>
          <span className="avatar">{initials(user)}</span>
        </header>

        <main className="main">
          <Outlet />
        </main>

        <nav className="bottom-nav" aria-label="Main">
          {NAV.map((item) => (
            <NavLink key={item.to} to={item.to} end={item.end}>
              <Icon name={item.icon} size={18} />
              <span>{item.label}</span>
            </NavLink>
          ))}
        </nav>
      </div>

      {drawerOpen && (
        <div className="drawer-backdrop" onClick={closeDrawer}>
          <aside className="sidebar drawer" onClick={(event) => event.stopPropagation()}>
            <SidebarContent user={user} onNavigate={closeDrawer} onLogout={logout} />
          </aside>
        </div>
      )}
    </div>
  );
}
