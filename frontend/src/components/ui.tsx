import type { ReactNode } from "react";
import type { ApiError } from "../api/client";

export function PageHeader({ title, subtitle }: { title: string; subtitle?: ReactNode }) {
  return (
    <header className="page-header">
      <h1>{title}</h1>
      {subtitle && <p>{subtitle}</p>}
    </header>
  );
}

export type BadgeKind = "ok" | "warn" | "fail" | "info";

export function Badge({ kind = "info", children }: { kind?: BadgeKind; children: ReactNode }) {
  return <span className={`badge badge-${kind}`}>{children}</span>;
}

export function KpiCard({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="kpi-card">
      <div className="kpi-label">{label}</div>
      <div className="kpi-value">{value ?? "—"}</div>
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

export function Loading() {
  return <p className="muted">Loading…</p>;
}

export function ErrorNotice({ error }: { error: ApiError }) {
  const text = error.status === 403 ? "You are not authorised to view this page." : error.message;
  return <Notice kind="fail">{text}</Notice>;
}

export interface Column<T> {
  header: string;
  render: (row: T) => ReactNode;
}

export function DataTable<T>({ rows, columns, rowKey }: { rows: T[]; columns: Column<T>[]; rowKey: (row: T) => string }) {
  if (rows.length === 0) return <p className="muted">No records.</p>;
  return (
    <div className="table-wrap">
      <table className="data-table">
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c.header}>{c.header}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={rowKey(row)}>
              {columns.map((c) => (
                <td key={c.header}>{c.render(row)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
