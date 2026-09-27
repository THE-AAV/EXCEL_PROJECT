import { useState, type ReactNode } from "react";
import { BrowserRouter, Navigate, NavLink, Route, Routes, useLocation } from "react-router-dom";
import type { Role } from "./api";
import FilterBar from "./components/FilterBar";
import { when } from "./format";
import Account from "./pages/Account";
import Audit from "./pages/Audit";
import Checks from "./pages/Checks";
import Dashboard from "./pages/Dashboard";
import Import from "./pages/Import";
import Ledger from "./pages/Ledger";
import Login from "./pages/Login";
import Notes from "./pages/Notes";
import Orders from "./pages/Orders";
import Pnl from "./pages/Pnl";
import ProductNames from "./pages/ProductNames";
import Stock from "./pages/Stock";
import Users from "./pages/Users";
import { AuthProvider, can, DataProvider, useAuth, useData } from "./session";

interface Page { path: string; label: string; element: ReactNode; role: Role; reports?: boolean }

const PAGES: Page[] = [
  { path: "/", label: "Dashboard", element: <Dashboard />, role: "viewer", reports: true },
  { path: "/pnl", label: "Product P&L", element: <Pnl />, role: "viewer", reports: true },
  { path: "/stock", label: "Stock", element: <Stock />, role: "viewer", reports: true },
  { path: "/creditors", label: "Creditors (we pay)", element: <Ledger side="creditors" />, role: "viewer", reports: true },
  { path: "/debtors", label: "Debtors (we receive)", element: <Ledger side="debtors" />, role: "viewer", reports: true },
  { path: "/orders", label: "Orders", element: <Orders />, role: "viewer", reports: true },
  { path: "/notes", label: "Debit / credit notes", element: <Notes />, role: "viewer", reports: true },
  { path: "/checks", label: "Data checks", element: <Checks />, role: "viewer", reports: true },
  { path: "/product-names", label: "Product names", element: <ProductNames />, role: "viewer" },
  { path: "/import", label: "Import", element: <Import />, role: "admin" },
  { path: "/users", label: "Users", element: <Users />, role: "admin" },
  { path: "/audit", label: "Audit log", element: <Audit />, role: "admin" },
  { path: "/account", label: "My account", element: <Account />, role: "viewer" },
];

function Shell() {
  const { user, signOut } = useAuth();
  const { status, error, reports } = useData();
  const loc = useLocation();
  const [menu, setMenu] = useState(false);
  const pages = PAGES.filter((p) => can(user, p.role));
  const current = PAGES.find((p) => p.path === loc.pathname);

  return (
    <div className={`shell ${menu ? "menu-open" : ""}`}>
      <aside className="sidebar" onClick={() => setMenu(false)}>
        <div className="brand"><span className="logo" /> Business Reports</div>
        <nav>
          {pages.map((p, i) => (
            <div key={p.path}>
              {i > 0 && p.role !== pages[i - 1].role && p.path !== "/account" && <div className="nav-sep">Admin</div>}
              {p.path === "/account" && <div className="nav-sep" />}
              <NavLink to={p.path} end>{p.label}</NavLink>
            </div>
          ))}
        </nav>
        <div className="sidebar-foot">
          <div>{user!.full_name || user!.username}</div>
          <span className={`badge role-${user!.role}`}>{user!.role}</span>
          <button className="link" onClick={signOut}>Sign out</button>
        </div>
      </aside>
      <main>
        <header className="topbar">
          <button className="menu-toggle" onClick={() => setMenu(!menu)} aria-label="Menu">☰</button>
          <div>
            <h1>{current?.label ?? ""}</h1>
            {status?.source && (
              <div className="muted small">
                Data from <b>{status.source.filename}</b>, imported {when(status.source.loaded_at)}
                {reports && <> · {reports.dashboard.purchase_bills} purchase bills · {reports.dashboard.sales_bills} sales bills</>}
              </div>
            )}
          </div>
        </header>
        {current?.reports && status?.has_data && <FilterBar />}
        {current?.reports && error && <div className="error">{error}</div>}
        <div className="content">
          <Routes>
            {pages.map((p) => <Route key={p.path} path={p.path} element={p.element} />)}
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </div>
      </main>
    </div>
  );
}

function Gate() {
  const { user, loading } = useAuth();
  if (loading) return null;
  if (!user) return <Login />;
  return (
    <DataProvider key={user.id}>
      <Shell />
    </DataProvider>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Gate />
      </AuthProvider>
    </BrowserRouter>
  );
}
