import { isValidElement, useEffect, useMemo, useState, type ReactNode } from "react";
import { useToast } from "./feedback";
import type { ApiError } from "../api/client";

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="page-header">
      <div>
        <h1>{title}</h1>
        {subtitle && <p>{subtitle}</p>}
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </header>
  );
}

export type BadgeKind = "ok" | "warn" | "fail" | "info";

export function Badge({ kind = "info", children }: { kind?: BadgeKind; children: ReactNode }) {
  return <span className={`badge badge-${kind}`}>{children}</span>;
}

export type KpiTone = "ok" | "warn" | "fail" | "info" | "brand";

/** A key number. `tone` colours it by meaning (green good, amber watch, red act); `hint` is a short line under it. */
export function KpiCard({ label, value, tone, hint }: { label: string; value: ReactNode; tone?: KpiTone; hint?: ReactNode }) {
  return (
    <div className={`kpi-card${tone ? ` kpi-${tone}` : ""}`}>
      <div className="kpi-label">{label}</div>
      <div className="kpi-value">{value ?? "—"}</div>
      {hint && <div className="kpi-hint">{hint}</div>}
    </div>
  );
}

export function Notice({ kind = "info", children }: { kind?: BadgeKind; children: ReactNode }) {
  return (
    <div className={`notice notice-${kind}`} role={kind === "fail" ? "alert" : "status"}>
      {children}
    </div>
  );
}

/** Grey placeholder blocks while a screen loads (instead of a bare "Loading..."). */
export function Loading({ lines = 3 }: { lines?: number }) {
  return (
    <div className="skeleton" role="status" aria-label="Loading">
      <div className="sk sk-row">{[0, 1, 2, 3].map((i) => <div key={i} className="sk sk-kpi" />)}</div>
      {Array.from({ length: lines }, (_, i) => <div key={i} className="sk sk-line" style={{ width: `${92 - i * 14}%` }} />)}
      <span className="sr-only">Loading…</span>
    </div>
  );
}

export function ErrorNotice({ error }: { error: ApiError }) {
  const text = error.status === 403 ? "You are not authorised to view this page." : error.message;
  return <Notice kind="fail">{text}</Notice>;
}

export interface Column<T> {
  header: string;
  render: (row: T) => ReactNode;
  /** Value used to sort / search / export this column (default: the text of what `render` shows). */
  value?: (row: T) => string | number | null | undefined;
  /** false: this column cannot be sorted (e.g. action buttons). */
  sortable?: boolean;
}

/** Plain text of a rendered cell (for sorting, searching and CSV export of any column). */
export function textOf(node: ReactNode): string {
  if (node === null || node === undefined || typeof node === "boolean") return "";
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(textOf).join(" ").replace(/\s+/g, " ").trim();
  if (isValidElement(node)) return textOf((node.props as { children?: ReactNode }).children);
  return "";
}

function cellValue<T>(c: Column<T>, row: T): string | number {
  const v = c.value ? c.value(row) : textOf(c.render(row));
  return v === null || v === undefined ? "" : v;
}

function compare(a: string | number, b: string | number): number {
  if (typeof a === "number" && typeof b === "number") return a - b;
  const na = Number(String(a).replace(/[%,]/g, "")), nb = Number(String(b).replace(/[%,]/g, ""));
  if (String(a).trim() !== "" && String(b).trim() !== "" && !Number.isNaN(na) && !Number.isNaN(nb)) return na - nb;
  return String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: "base" });
}

function downloadCsv<T>(name: string, rows: T[], columns: Column<T>[]) {
  const q = (v: string | number) => `"${String(v).replace(/"/g, '""')}"`;
  const cols = columns.filter((c) => c.header.trim() && c.sortable !== false);
  const lines = [cols.map((c) => q(c.header)).join(",")].concat(rows.map((r) => cols.map((c) => q(cellValue(c, r))).join(",")));
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob(["﻿" + lines.join("\r\n")], { type: "text/csv" }));
  a.download = `${name}.csv`;
  document.body.appendChild(a);
  a.click();
  a.remove();
}

/**
 * Table with sortable columns (click a header), optional quick search, paging and CSV export of the rows shown.
 * `search`: show a search box; `exportName`: show "Export CSV"; `pageSize`: rows per page (0 = all).
 */
export function DataTable<T>({ rows, columns, rowKey, search = false, exportName, pageSize = 50, empty }: {
  rows: T[]; columns: Column<T>[]; rowKey: (row: T) => string; search?: boolean; exportName?: string; pageSize?: number; empty?: ReactNode;
}) {
  const [sort, setSort] = useState<{ col: number; dir: 1 | -1 } | null>(null);
  const [q, setQ] = useState("");
  const [page, setPage] = useState(0);
  useEffect(() => setPage(0), [q, rows.length, sort]);

  const shown = useMemo(() => {
    let out = rows;
    const needle = q.trim().toLowerCase();
    if (needle) out = out.filter((r) => columns.some((c) => String(cellValue(c, r)).toLowerCase().includes(needle)));
    if (sort) {
      const c = columns[sort.col];
      out = [...out].sort((a, b) => compare(cellValue(c, a), cellValue(c, b)) * sort.dir);
    }
    return out;
  }, [rows, columns, q, sort]);

  const pages = pageSize > 0 ? Math.max(1, Math.ceil(shown.length / pageSize)) : 1;
  const start = pageSize > 0 ? page * pageSize : 0;
  const visible = pageSize > 0 ? shown.slice(start, start + pageSize) : shown;
  const toggle = (i: number) => setSort((s) => (s && s.col === i ? (s.dir === 1 ? { col: i, dir: -1 } : null) : { col: i, dir: 1 }));

  if (rows.length === 0) {
    return (
      <div className="empty">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.6} aria-hidden="true"><path d="M3 13h5l1.5 3h5L16 13h5M5 5h14l2 8v6H3v-6z" /></svg>
        <span>{empty ?? "Nothing to show yet."}</span>
      </div>
    );
  }
  return (
    <div className="dt">
      {(search || exportName) && (
        <div className="dt-bar">
          {search && <input className="dt-search" type="search" placeholder="Search this table…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search this table" />}
          <span className="dt-count">{shown.length === rows.length ? `${rows.length} rows` : `${shown.length} of ${rows.length} rows`}</span>
          {exportName && (
            <button type="button" className="btn btn-ghost btn-small" onClick={() => downloadCsv(exportName, shown, columns)}>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden="true"><path d="M12 4v11M7 10l5 5 5-5M5 20h14" /></svg> Export CSV
            </button>
          )}
        </div>
      )}
      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              {columns.map((c, i) => {
                const can = c.sortable !== false && c.header.trim() !== "";
                const dir = sort?.col === i ? (sort.dir === 1 ? "ascending" : "descending") : "none";
                return (
                  <th key={`${c.header}-${i}`} aria-sort={can ? dir : undefined}>
                    {can ? (
                      <button type="button" className={`th-sort${dir !== "none" ? " on" : ""}`} onClick={() => toggle(i)} aria-label={`Sort by ${c.header}`} title="Sort">
                        {c.header}<span className="th-arrow" aria-hidden="true">{dir === "ascending" ? "▲" : dir === "descending" ? "▼" : "↕"}</span>
                      </button>
                    ) : c.header}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {visible.map((row) => (
              <tr key={rowKey(row)}>
                {columns.map((c, i) => (
                  <td key={`${c.header}-${i}`}>{c.render(row)}</td>
                ))}
              </tr>
            ))}
            {visible.length === 0 && (
              <tr><td colSpan={columns.length} className="dt-none">No rows match “{q}”.</td></tr>
            )}
          </tbody>
        </table>
      </div>
      {pages > 1 && (
        <div className="dt-pager">
          <span>{start + 1}–{Math.min(start + pageSize, shown.length)} of {shown.length}</span>
          <button type="button" className="btn btn-ghost btn-small" disabled={page === 0} onClick={() => setPage((p) => p - 1)}>‹ Previous</button>
          <span className="muted">Page {page + 1} of {pages}</span>
          <button type="button" className="btn btn-ghost btn-small" disabled={page >= pages - 1} onClick={() => setPage((p) => p + 1)}>Next ›</button>
        </div>
      )}
    </div>
  );
}

const STATUS_KIND: Record<string, BadgeKind> = {
  PRESENT: "ok", WORK_FROM_HOME: "ok", VALID: "ok", VERIFIED: "ok", RESOLVED: "ok", APPROVED: "ok", MATCHED: "ok",
  READY_FOR_REVIEW: "info", COMPLETED: "ok", DISTRIBUTED: "ok", GENERATED: "info", READY_FOR_PROCESSING: "ok", OK: "ok",
  ABSENT: "fail", FAILED: "fail", REJECTED: "fail", HIGH: "fail", CRITICAL: "fail", DELIVERY_FAILED: "fail", FAIL: "fail",
  UNRESOLVED: "warn", PENDING: "warn", PENDING_REVIEW: "warn", REQUIRES_REVIEW: "warn", MISSING_PUNCH: "warn",
  PENDING_APPROVAL: "warn", STATUS_CONFLICT: "warn", LEAVE_CONFLICT: "warn", EMPLOYEE_MAPPING_MISSING: "fail",
  MEDIUM: "warn", WARN: "warn", PROVISIONAL: "warn", NOT_APPROVED: "warn", PENDING_DISCOVERY: "warn", UNAVAILABLE: "warn",
  SENT: "ok", SAVED: "info", NO_RECIPIENTS: "warn", NOT_TRACKED: "info", LEAVE: "info", ON_DUTY: "ok", HALF_DAY: "info",
};

/** Badge whose colour follows the value (status words from the API). */
export function StatusBadge({ value }: { value: string | null | undefined }) {
  if (!value) return <span className="muted">—</span>;
  return <Badge kind={STATUS_KIND[value] ?? "info"}>{value.replace(/_/g, " ")}</Badge>;
}

export function Toolbar({ children }: { children: ReactNode }) {
  return <div className="toolbar">{children}</div>;
}

export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return (
    <label className="field">
      <span className="field-label">{label}</span>
      {children}
      {hint && <span className="field-hint">{hint}</span>}
    </label>
  );
}

export function Card({ title, children, actions }: { title?: string; children: ReactNode; actions?: ReactNode }) {
  return (
    <section className="card">
      {(title || actions) && (
        <div className="card-head">
          {title && <h3>{title}</h3>}
          {actions}
        </div>
      )}
      {children}
    </section>
  );
}

/** Success -> a short pop-up message; an error stays on the page next to the form (and pops up too). */
export function ActionMessages({ error, message }: { error: string | null; message: string | null }) {
  const toast = useToast();
  useEffect(() => { if (message) toast(message, "ok"); }, [message, toast]);
  useEffect(() => { if (error) toast(error, "fail"); }, [error, toast]);
  return error ? <Notice kind="fail">{error}</Notice> : null;
}

export function pct(v: number | null | undefined): string {
  return v === null || v === undefined ? "Pending HR approval" : `${v.toFixed(2)}%`;
}
