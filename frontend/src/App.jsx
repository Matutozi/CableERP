import { Navigate, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout.jsx";
import { useAuth } from "./context/AuthContext.jsx";
import Accessories from "./pages/Accessories.jsx";
import Catalogue from "./pages/Catalogue.jsx";
import Dashboard from "./pages/Dashboard.jsx";
import Login from "./pages/Login.jsx";
import QuoteEditor from "./pages/QuoteEditor.jsx";
import QuoteList from "./pages/QuoteList.jsx";
import Purchases from "./pages/Purchases.jsx";
import QuotePreview from "./pages/QuotePreview.jsx";
import AcceptInvite from "./pages/AcceptInvite.jsx";
import Staff from "./pages/Staff.jsx";
import WaybillPreview from "./pages/WaybillPreview.jsx";
import Register from "./pages/Register.jsx";
import Settings from "./pages/Settings.jsx";
import WaybillEditor from "./pages/WaybillEditor.jsx";
import WaybillList from "./pages/WaybillList.jsx";

export default function App() {
  const { user } = useAuth();

  if (user === undefined) return <div className="page-loading">Loading…</div>;

  return (
    <Routes>
      <Route path="/login" element={user ? <Navigate to="/" replace /> : <Login />} />
      <Route path="/register" element={user ? <Navigate to="/" replace /> : <Register />} />
      {/* Reachable signed out: the invited person has no account yet. */}
      <Route path="/invite/:token" element={<AcceptInvite />} />
      <Route element={user ? <Layout /> : <Navigate to="/login" replace />}>
        <Route index element={<Dashboard />} />
        <Route path="quotes" element={<QuoteList />} />
        <Route path="quotes/new" element={<QuoteEditor />} />
        <Route path="quotes/waybills" element={<WaybillList />} />
        <Route path="quotes/waybills/:id" element={<WaybillEditor />} />
        <Route path="quotes/waybills/:id/preview" element={<WaybillPreview />} />
        <Route path="quotes/:id" element={<QuoteEditor />} />
        <Route path="quotes/:id/preview" element={<QuotePreview />} />
        <Route path="catalogue" element={<Catalogue />} />
        <Route path="catalogue/accessories" element={<Accessories />} />
        <Route path="catalogue/purchases" element={<Purchases />} />
        <Route path="staff" element={<Staff />} />
        <Route path="settings" element={<Settings />} />
        <Route path="business" element={<Navigate to="/settings" replace />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
