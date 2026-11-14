import { useState } from "react";
import { api } from "../api/client";
import { useDefaultDate } from "../api/dates";
import { useAction, useApi, withQuery } from "../api/useApi";
import type { EmployeeRow, ExceptionRow, MappingRow, ReconRow, RunInfo } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { STATUS_LABELS, STATUS_ORDER } from "../components/charts";
import { ActionMessages, Card, DataTable, ErrorNotice, Field, KpiCard, Loading, Notice, PageHeader, StatusBadge, Toolbar } from "../components/ui";
import { formatDate, formatDateTime } from "../format";

const CATEGORIES = ["STATUS_CONFLICT", "LEAVE_CONFLICT", "TIME_CONFLICT", "BIZOM_ONLY", "HRMS_ONLY", "EMPLOYEE_MAPPING_MISSING", "DUPLICATE_RECORD", "MATCHED"];

// ------------------------------------------------------------------ Source Comparison
export function SourceComparisonPage() {
  const [day, setDay] = useDefaultDate();
  const [category, setCategory] = useState("");
  const data = useApi<{ run: RunInfo | null; rows: ReconRow[] }>(day ? withQuery("/v1/reconciliation", { date: day, category }) : null);
  const counts = (data.data?.rows ?? []).reduce((a, r) => ({ ...a, [r.category]: (a[r.category] ?? 0) + 1 }), {} as Record<string, number>);
  return (
    <>
      <PageHeader title="Source Comparison" subtitle="Bizom vs Pocket HRMS per employee and date" />
      <Toolbar>
        <Field label="Date"><input type="date" value={day} onChange={(e) => setDay(e.target.value)} /></Field>
        <Field label="Category">
          <select value={category} onChange={(e) => setCategory(e.target.value)}>
            <option value="">All</option>
            {CATEGORIES.map((c) => <option key={c} value={c}>{c.replace(/_/g, " ")}</option>)}
          </select>
        </Field>
      </Toolbar>
      {data.loading && <Loading />}
      {data.error && <ErrorNotice error={data.error} />}
      {data.data && !data.data.run && <Notice>No processed run for {formatDate(day)}.</Notice>}
      {data.data?.run && (
        <>
          {!category && <div className="kpi-grid">{Object.entries(counts).map(([c, n]) => <KpiCard key={c} label={c.replace(/_/g, " ")} value={n} />)}</div>}
          <ReconTable rows={data.data.rows} />
        </>
      )}
    </>
  );
}

function ReconTable({ rows }: { rows: ReconRow[] }) {
  return (
    <DataTable rows={rows} rowKey={(r) => String(r.id)} columns={[
      { header: "Category", render: (r) => <StatusBadge value={r.category} /> },
      { header: "Employee / source id", render: (r) => r.source_employee_id ?? "" },
      { header: "Bizom", render: (r) => r.bizom ?? "—" },
      { header: "Pocket HRMS", render: (r) => r.hrms ?? "—" },
      { header: "Detail", render: (r) => r.detail ?? "" },
    ]} />
  );
}

// ------------------------------------------------------------------ Conflicting Records
export function ConflictsPage() {
  const [day, setDay] = useDefaultDate();
  const conflicts = useApi<{ run: RunInfo | null; rows: ReconRow[] }>(day ? withQuery("/v1/reconciliation", { date: day }) : null);
  const rows = (conflicts.data?.rows ?? []).filter((r) => ["STATUS_CONFLICT", "LEAVE_CONFLICT", "TIME_CONFLICT", "DUPLICATE_RECORD"].includes(r.category));
  return (
    <>
      <PageHeader title="Conflicting Records" subtitle="Where the sources disagree" />
      <Toolbar><Field label="Date"><input type="date" value={day} onChange={(e) => setDay(e.target.value)} /></Field></Toolbar>
      {conflicts.error && <ErrorNotice error={conflicts.error} />}
      {conflicts.data && (rows.length ? <ReconTable rows={rows} /> : <Notice kind="ok">No conflicts for {formatDate(day)}.</Notice>)}
    </>
  );
}

// ------------------------------------------------------------------ Unmapped Employees / Employee Mapping
export function MappingTable({ status }: { status: string }) {
  const list = useApi<MappingRow[]>(withQuery("/v1/mappings", { status_filter: status }));
  const [search, setSearch] = useState("");
  const [choice, setChoice] = useState<Record<number, string>>({});
  const employees = useApi<EmployeeRow[]>(withQuery("/v1/employees", { search }));
  const act = useAction();

  async function resolve(m: MappingRow, reject = false) {
    const key = reject ? null : Number(choice[m.mapping_id] ?? m.suggested_employee_key);
    const r = await act.run(() => api.post(`/v1/mappings/${m.mapping_id}/resolve`, { employee_key: key, reject }),
      reject ? `Mapping for ${m.source_employee_id} rejected.` : `${m.source_employee_id} mapped. Re-run processing to apply.`);
    if (r) list.reload();
  }
  return (
    <>
      <Toolbar>
        <Field label="Find employee (for the picker)"><input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="code or name" /></Field>
      </Toolbar>
      <ActionMessages error={act.error} message={act.message} />
      {list.loading && <Loading />}
      {list.error && <ErrorNotice error={list.error} />}
      {list.data && (
        <DataTable rows={list.data} rowKey={(m) => String(m.mapping_id)} columns={[
          { header: "Source", render: (m) => m.source_system.replace("_", " ") },
          { header: "Source id", render: (m) => <><strong>{m.source_employee_id}</strong><div className="muted small">{m.source_employee_name}</div></> },
          { header: "Status", render: (m) => <StatusBadge value={m.status} /> },
          { header: "Mapped to", render: (m) => m.employee ?? "—" },
          { header: "Suggestion (name only)", render: (m) => m.suggested_employee ? `${m.suggested_employee} (${Math.round((m.confidence ?? 0) * 100)}%)` : "—" },
          { header: "Resolve", render: (m) => m.status === "PENDING" ? (
            <div className="inline-actions">
              <select value={choice[m.mapping_id] ?? String(m.suggested_employee_key ?? "")} onChange={(e) => setChoice({ ...choice, [m.mapping_id]: e.target.value })}>
                <option value="">Select employee…</option>
                {m.suggested_employee_key && <option value={m.suggested_employee_key}>{m.suggested_employee} (suggested)</option>}
                {employees.data?.map((e) => <option key={e.employee_key} value={e.employee_key}>{e.employee_code} — {e.employee_name}</option>)}
              </select>
              <button className="btn btn-primary btn-small" disabled={act.busy || !(choice[m.mapping_id] ?? m.suggested_employee_key)} onClick={() => void resolve(m)}>Verify</button>
              <button className="btn btn-ghost btn-small" disabled={act.busy} onClick={() => void resolve(m, true)}>Reject</button>
            </div>
          ) : <span className="muted small">{m.method} {m.reviewed_by ? `by ${m.reviewed_by}` : ""}</span> },
        ]} />
      )}
    </>
  );
}

export function UnmappedEmployeesPage() {
  return (
    <>
      <PageHeader title="Unmapped Employees" subtitle="Source ids without a verified employee. Name matches are suggestions only; a person must verify." />
      <MappingTable status="PENDING" />
    </>
  );
}

// ------------------------------------------------------------------ Exception Resolution
export function ExceptionResolutionPage() {
  const [statusFilter, setStatusFilter] = useState("OPEN");
  const [category, setCategory] = useState("");
  const list = useApi<ExceptionRow[]>(withQuery("/v1/exceptions", { status: statusFilter, category }));
  const [open, setOpen] = useState<ExceptionRow | null>(null);
  const history = useApi<{ from: string; to: string; actor: string; comment: string | null; at: string }[]>(open ? `/v1/exceptions/${open.exception_id}/history` : null);
  const [decision, setDecision] = useState("ADJUST");
  const [adjusted, setAdjusted] = useState("PRESENT");
  const [comment, setComment] = useState("");
  const act = useAction();
  const { hasPermission, me } = useAuth();
  const canAct = hasPermission("RECONCILIATION_RESOLVE");

  async function action(body: Record<string, unknown>, msg: string) {
    if (!open) return;
    const r = await act.run(() => api.post<ExceptionRow>(`/v1/exceptions/${open.exception_id}/action`, body), msg);
    if (r) {
      setOpen(r);
      list.reload();
      history.reload();
      setComment("");
    }
  }

  return (
    <>
      <PageHeader title="Exception Resolution" subtitle="Review, assign and resolve. Source values are never edited; adjustments apply on the next run." />
      <Toolbar>
        <Field label="Status">
          <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
            <option value="OPEN">Open</option>
            {["PENDING_REVIEW", "ASSIGNED", "UNDER_REVIEW", "RESOLVED", "REJECTED", "SUPERSEDED"].map((s) => <option key={s} value={s}>{s.replace(/_/g, " ")}</option>)}
            <option value="">All</option>
          </select>
        </Field>
        <Field label="Category">
          <select value={category} onChange={(e) => setCategory(e.target.value)}>
            <option value="">All</option>
            {CATEGORIES.filter((c) => c !== "MATCHED").map((c) => <option key={c} value={c}>{c.replace(/_/g, " ")}</option>)}
          </select>
        </Field>
      </Toolbar>
      {list.loading && <Loading />}
      {list.error && <ErrorNotice error={list.error} />}
      {list.data && (
        <DataTable rows={list.data} rowKey={(x) => String(x.exception_id)} columns={[
          { header: "#", render: (x) => <button className="link" onClick={() => setOpen(x)}>{x.exception_id}</button> },
          { header: "Date", render: (x) => formatDate(x.date) },
          { header: "Category", render: (x) => <StatusBadge value={x.category} /> },
          { header: "Severity", render: (x) => <StatusBadge value={x.severity} /> },
          { header: "Employee / id", render: (x) => x.source_employee_id ?? "" },
          { header: "Dept", render: (x) => x.department_code ?? "" },
          { header: "Detail", render: (x) => <span className="small">{x.source_values.detail}</span> },
          { header: "Status", render: (x) => <StatusBadge value={x.status} /> },
          { header: "Assigned", render: (x) => x.assigned_to ?? "" },
        ]} />
      )}
      {open && (
        <Card title={`Exception #${open.exception_id} — ${open.category.replace(/_/g, " ")}`} actions={<button className="btn btn-ghost btn-small" onClick={() => setOpen(null)}>Close</button>}>
          <ul className="kv-list">
            <li><span>Employee / source id</span><strong>{open.source_employee_id}</strong></li>
            <li><span>Date</span><strong>{formatDate(open.date)}</strong></li>
            <li><span>Bizom value</span><strong>{open.source_values.bizom ?? "—"}</strong></li>
            <li><span>Pocket HRMS value</span><strong>{open.source_values.hrms ?? "—"}</strong></li>
            <li><span>Detail</span><span>{open.source_values.detail}</span></li>
            <li><span>Status</span><StatusBadge value={open.status} /></li>
            {open.resolution && <li><span>Resolution</span><span>{open.resolution} {open.resolved_status ?? ""} — {open.resolution_comment}</span></li>}
          </ul>
          <ActionMessages error={act.error} message={act.message} />
          {canAct && open.status === "PENDING_REVIEW" && (
            <button className="btn btn-primary btn-inline" disabled={act.busy} onClick={() => void action({ action: "ASSIGN", assignee: me?.username }, "Assigned to you.")}>Assign to me</button>
          )}
          {canAct && open.status === "ASSIGNED" && (
            <button className="btn btn-primary btn-inline" disabled={act.busy} onClick={() => void action({ action: "START" }, "Review started.")}>Start review</button>
          )}
          {canAct && open.status === "UNDER_REVIEW" && (
            <div className="form-grid">
              <Field label="Decision">
                <select value={open.employee_key === null && decision === "ADJUST" ? "NO_CHANGE" : decision} onChange={(e) => setDecision(e.target.value)}>
                  {open.employee_key !== null && <option value="ADJUST">Adjust the attendance status</option>}
                  <option value="NO_CHANGE">Resolve without change</option>
                  <option value="REJECT">Reject (not a real exception)</option>
                </select>
              </Field>
              {open.employee_key === null && (
                <Notice>This source id is not mapped to an employee, so its status cannot be adjusted. Map it under Unmapped Employees, then re-run processing.</Notice>
              )}
              {decision === "ADJUST" && open.employee_key !== null && (
                <Field label="Correct status">
                  <select value={adjusted} onChange={(e) => setAdjusted(e.target.value)}>
                    {STATUS_ORDER.map((s) => <option key={s} value={s}>{STATUS_LABELS[s]}</option>)}
                  </select>
                </Field>
              )}
              <Field label="Comment (required)"><textarea rows={3} value={comment} onChange={(e) => setComment(e.target.value)} /></Field>
              <div className="form-actions">
                <button className="btn btn-primary" disabled={act.busy || !comment.trim()}
                  onClick={() => {
                    const d = open.employee_key === null && decision === "ADJUST" ? "NO_CHANGE" : decision;
                    void action({ action: "RESOLVE", decision: d, adjusted_status: d === "ADJUST" ? adjusted : null, comment }, "Exception closed.");
                  }}>
                  Submit
                </button>
              </div>
            </div>
          )}
          <h3>Audit trail</h3>
          {history.data && (
            <DataTable rows={history.data} rowKey={(h) => `${h.at}-${h.to}`} columns={[
              { header: "When", render: (h) => formatDateTime(h.at) }, { header: "From", render: (h) => h.from },
              { header: "To", render: (h) => <StatusBadge value={h.to} /> }, { header: "By", render: (h) => h.actor },
              { header: "Comment", render: (h) => h.comment ?? "" }]} />
          )}
        </Card>
      )}
    </>
  );
}
