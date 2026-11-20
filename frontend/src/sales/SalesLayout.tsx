import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { BrandMark } from "../components/Brand";
import { Icon } from "../components/icons";

// Module 2 menu. Same look as Module 1's layout (shared CSS classes), its own pages under /sales.
export const SALES_PAGES = [
  { section: "Field sales", title: "Overview", path: "/sales", icon: "home", end: true },
  { section: "Field sales", title: "Upload", path: "/sales/upload", icon: "upload", perm: "UPLOAD_AND_SEND" },
  { section: "Field sales", title: "Day insights", path: "/sales/day", icon: "insights" },
  { section: "Field sales", title: "Approve emails", path: "/sales/mail", icon: "mail" },
  { section: "Reports", title: "Attendance report", path: "/sales/report", icon: "reports" },
  { section: "Reports", title: "Employee report", path: "/sales/employee", icon: "employee-report" },
  { section: "Reports", title: "Email log", path: "/sales/emails", icon: "emails" },
  { section: "Setup", title: "Staff list", path: "/sales/staff", icon: "employees" },
  { section: "Setup", title: "Automation", path: "/sales/automation", icon: "automation" },
  { section: "Setup", title: "Settings", path: "/sales/settings", icon: "settings", perm: "MANAGE_SETTINGS" },
] as const;

export function SalesLayout() {
  const { me, logout, hasPermission } = useAuth();
  const location = useLocation();
  const [navOpen, setNavOpen] = useState(false);
  useEffect(() => { setNavOpen(false); }, [location.pathname]);
  if (!me) return null;
  const pages = SALES_PAGES.filter((p) => !("perm" in p) || hasPermission(p.perm));
  const current = [...pages].reverse().find((p) => location.pathname === p.path || location.pathname.startsWith(`${p.path}/`));
  const sections = [...new Set(pages.map((p) => p.section))];

  return (
    <div className={`shell sales-module${navOpen ? " nav-open" : ""}`}>
      <aside className="sidebar" aria-label="Field sales navigation">
        <div className="sidebar-brand">
          <BrandMark />
          <div className="sidebar-brand-text">
            <span className="sidebar-product">Field Sales</span>
            <span className="sidebar-company">HR Portal · Bizom</span>
          </div>
        </div>
        <nav>
          {sections.map((section) => (
            <div className="nav-section" key={section}>
              <div className="nav-section-title">{section}</div>
              {pages.filter((p) => p.section === section).map((p) => (
                <NavLink key={p.path} to={p.path} end={"end" in p} className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")}>
                  <Icon name={p.icon} />
                  <span>{p.title}</span>
                </NavLink>
              ))}
            </div>
          ))}
        </nav>
        <NavLink to="/modules" className="nav-link switch-module">
          <Icon name="switch" />
          <span>Switch module</span>
        </NavLink>
        <div className="sidebar-footer"><span className="dot" aria-hidden="true" />Field Sales attendance</div>
      </aside>
      <div className="scrim" onClick={() => setNavOpen(false)} aria-hidden="true" />
      <div className="main">
        <header className="topbar">
          <button type="button" className="menu-btn" aria-label={navOpen ? "Close menu" : "Open menu"} aria-expanded={navOpen}
            onClick={() => setNavOpen((v) => !v)}>
            <Icon name={navOpen ? "close" : "menu"} />
          </button>
          <div className="crumbs">
            <span className="section">Field Sales</span><span className="sep" aria-hidden="true">/</span>
            <strong>{current?.title ?? "Overview"}</strong>
          </div>
          <div className="topbar-right">
            {me.environment !== "production" && <span className="env-chip">{me.environment}</span>}
            <span className="user-name hide-sm">{me.display_name}</span>
            {me.auth_mode === "local" && (
              <button type="button" className="btn btn-ghost btn-small" onClick={() => void logout()}>
                <Icon name="logout" className="btn-icon" /> Sign out
              </button>
            )}
          </div>
        </header>
        <main className="content"><Outlet /></main>
      </div>
    </div>
  );
}
