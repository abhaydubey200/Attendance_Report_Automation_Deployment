import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import type { NavPage } from "../api/types";

function groupBySection(pages: NavPage[]): [string, NavPage[]][] {
  const groups = new Map<string, NavPage[]>();
  for (const page of pages) {
    const list = groups.get(page.section) ?? [];
    list.push(page);
    groups.set(page.section, list);
  }
  return [...groups.entries()];
}

export function Layout() {
  const { me, logout } = useAuth();
  if (!me) return null;

  return (
    <div className="shell">
      <aside className="sidebar" aria-label="Main navigation">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true" />
          <span>APIS ATTENDANCE MIS</span>
        </div>
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
        <div className="sidebar-footer">
          <div className="user-name">{me.display_name}</div>
          <div className="user-roles">{me.roles.join(", ") || "No role"}</div>
          {me.environment !== "production" && <div className="env-tag">{me.environment.toUpperCase()} ENVIRONMENT</div>}
          <button type="button" className="btn btn-secondary" onClick={() => void logout()}>
            Sign out
          </button>
        </div>
      </aside>
      <main className="content">
        <Outlet />
      </main>
    </div>
  );
}
