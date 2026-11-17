import type { ReactNode } from "react";
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

export function Loading() {
  return <p className="muted" role="status">Loading…</p>;
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
  if (rows.length === 0) {
    return (
      <div className="empty">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.6} aria-hidden="true"><path d="M3 13h5l1.5 3h5L16 13h5M5 5h14l2 8v6H3v-6z" /></svg>
        <span>Nothing to show.</span>
      </div>
    );
  }
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

export function ActionMessages({ error, message }: { error: string | null; message: string | null }) {
  return (
    <>
      {error && <Notice kind="fail">{error}</Notice>}
      {message && <Notice kind="ok">{message}</Notice>}
    </>
  );
}

export function pct(v: number | null | undefined): string {
  return v === null || v === undefined ? "Pending HR approval" : `${v.toFixed(2)}%`;
}
