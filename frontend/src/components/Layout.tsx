import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import type { NavPage } from "../api/types";
import { BrandMark } from "./Brand";
import { Icon } from "./icons";

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
  const location = useLocation();
  const [navOpen, setNavOpen] = useState(false);
  useEffect(() => setNavOpen(false), [location.pathname]);          // close the phone menu after choosing a page
  if (!me) return null;
  const signInMode = me.auth_mode === "local";
  const current = me.navigation.find((p) => location.pathname.startsWith(`/${p.slug}`));

  return (
    <div className={`shell${navOpen ? " nav-open" : ""}`}>
      <aside className="sidebar" aria-label="Main navigation">
        <div className="sidebar-brand">
          <BrandMark />
          <div className="sidebar-brand-text">
            <span className="sidebar-product">HR Portal</span>
            <span className="sidebar-company">APIS India Limited</span>
          </div>
        </div>
        <nav>
          {groupBySection(me.navigation).map(([section, pages]) => (
            <div className="nav-section" key={section}>
              <div className="nav-section-title">{section}</div>
              {pages.map((page) => (
                <NavLink key={page.slug} to={`/${page.slug}`} className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")}>
                  <Icon name={page.slug} />
                  <span>{page.title}</span>
                  {!page.implemented && <span className="nav-phase">P{page.phase}</span>}
                </NavLink>
              ))}
            </div>
          ))}
        </nav>
        <NavLink to="/modules" className="nav-link switch-module">
          <Icon name="switch" />
          <span>Switch module</span>
        </NavLink>
        <div className="sidebar-footer">
          <span className="dot" aria-hidden="true" />
          {signInMode ? "Signed-in access" : "Local access · this PC only"}
        </div>
      </aside>
      <div className="scrim" onClick={() => setNavOpen(false)} aria-hidden="true" />

      <div className="main">
        <header className="topbar">
          <button type="button" className="menu-btn" aria-label={navOpen ? "Close menu" : "Open menu"} aria-expanded={navOpen}
            onClick={() => setNavOpen((v) => !v)}>
            <Icon name={navOpen ? "close" : "menu"} />
          </button>
          <div className="crumbs">
            {current && <span className="section">{current.section}</span>}
            {current && <span className="sep" aria-hidden="true">/</span>}
            <strong>{current?.title ?? "HR Portal"}</strong>
          </div>
          <div className="topbar-right">
            {me.environment !== "production" && <span className="env-chip">{me.environment}</span>}
            <div className="user-chip" title={me.roles.join(", ")}>
              <span className="avatar" aria-hidden="true">{initials(me.display_name)}</span>
              <span className="user-chip-text">
                <span className="user-name">{me.display_name}</span>
                <span className="user-roles">{me.roles.map((r) => r.replace(/_/g, " ").toLowerCase()).join(" · ")}</span>
              </span>
            </div>
            {signInMode && (
              <button type="button" className="btn btn-ghost btn-small" onClick={() => void logout()}>
                <Icon name="logout" className="btn-icon" /> Sign out
              </button>
            )}
          </div>
        </header>
        <main className="content">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
