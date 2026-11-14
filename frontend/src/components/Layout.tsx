import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import type { NavPage } from "../api/types";
import { BrandMark } from "./Brand";

function groupBySection(pages: NavPage[]): [string, NavPage[]][] {
  const groups = new Map<string, NavPage[]>();
  for (const page of pages) {
    const list = groups.get(page.section) ?? [];
    list.push(page);
    groups.set(page.section, list);
  }
  return [...groups.entries()];
}

function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]!.toUpperCase())
    .join("");
}

export function Layout() {
  const { me, logout } = useAuth();
  if (!me) return null;
  const signInMode = me.auth_mode === "local";

  return (
    <div className="shell">
      <header className="topbar">
        <div className="topbar-brand">
          <BrandMark />
          <div className="topbar-title">
            <span className="topbar-product">Intelligent HR &amp; Attendance MIS</span>
            <span className="topbar-company">APIS India Limited</span>
          </div>
        </div>
        <div className="topbar-right">
          {me.environment !== "production" && <span className="env-chip">{me.environment}</span>}
          <div className="user-chip" title={me.roles.join(", ")}>
            <span className="avatar" aria-hidden="true">{initials(me.display_name)}</span>
            <span className="user-chip-text">
              <span className="user-name">{me.display_name}</span>
              <span className="user-roles">{me.roles.map((r) => r.replace(/_/g, " ")).join(" · ")}</span>
            </span>
          </div>
          {signInMode && (
            <button type="button" className="btn btn-ghost" onClick={() => void logout()}>
              Sign out
            </button>
          )}
        </div>
      </header>

      <div className="body">
        <aside className="sidebar" aria-label="Main navigation">
          <nav>
            {groupBySection(me.navigation).map(([section, pages]) => (
              <div className="nav-section" key={section}>
                <div className="nav-section-title">{section}</div>
                {pages.map((page) => (
                  <NavLink key={page.slug} to={`/${page.slug}`} className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")}>
                    <span>{page.title}</span>
                    {!page.implemented && <span className="nav-phase">P{page.phase}</span>}
                  </NavLink>
                ))}
              </div>
            ))}
          </nav>
          <div className="sidebar-footer">{signInMode ? "Signed-in access" : "Local access · no sign-in"}</div>
        </aside>
        <main className="content">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
