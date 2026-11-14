import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useDefaultDate } from "../api/dates";
import { useAction, useApi } from "../api/useApi";
import type { EmployeeRow, RunDetail, RunRow } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { ActionMessages, Badge, Card, DataTable, ErrorNotice, Field, KpiCard, Loading, Notice, PageHeader, StatusBadge, Toolbar } from "../components/ui";
import { formatDate, formatDateTime } from "../format";
import { MappingTable } from "./ReconciliationPages";

// ------------------------------------------------------------------ Processing Runs
export function ProcessingRunsPage() {
  const runs = useApi<RunRow[]>("/v1/runs");
  const [day, setDay] = useDefaultDate();
  const [openId, setOpenId] = useState<number | null>(null);
  const detail = useApi<RunDetail>(openId ? `/v1/runs/${openId}` : null);
  const act = useAction();
  const { hasPermission } = useAuth();

  async function call(path: string, msg: (r: Record<string, unknown>) => string) {
    const r = await act.run(() => api.post<Record<string, unknown>>(path, path.endsWith("/v1/runs") ? { reporting_date: day } : undefined), msg);
    if (r) {
      runs.reload();
      if (typeof r.run_id === "number") setOpenId(r.run_id);
      else detail.reload();
    }
  }

  return (
    <>
      <PageHeader title="Processing Runs" subtitle="Each run is a version of the results for a reporting date" />
      {hasPermission("REPORT_GENERATE") && (
        <Card title="Start processing">
          <Toolbar>
            <Field label="Reporting date"><input type="date" value={day} onChange={(e) => setDay(e.target.value)} /></Field>
            <button className="btn btn-primary btn-inline" disabled={act.busy || !day}
              onClick={() => void call("/v1/runs", (r) => (r.created ? `Run ${r.run_ref} finished: ${String(r.state).replace(/_/g, " ")}.` : `No input changed since ${r.run_ref}; existing run kept.`))}>
              {act.busy ? "Processing…" : "Process this date"}
            </button>
          </Toolbar>
          <p className="muted small">Identical inputs return the existing run; changed uploads, mappings, rules or resolved exceptions create a new version.</p>
        </Card>
      )}
      <ActionMessages error={act.error} message={act.message} />
      {runs.loading && <Loading />}
      {runs.error && <ErrorNotice error={runs.error} />}
      {runs.data && (
        <DataTable rows={runs.data} rowKey={(r) => String(r.run_id)} columns={[
          { header: "Run", render: (r) => <button className="link" onClick={() => setOpenId(r.run_id)}>{r.run_ref}</button> },
          { header: "Date", render: (r) => formatDate(r.reporting_date) },
          { header: "State", render: (r) => <StatusBadge value={r.state} /> },
          { header: "Current", render: (r) => (r.is_current ? <Badge kind="ok">CURRENT</Badge> : "") },
          { header: "Rules", render: (r) => `${r.rule_version}${r.rules_approved ? "" : " (provisional)"}` },
          { header: "AI", render: (r) => r.ai_status ?? "" },
          { header: "Started", render: (r) => `${formatDateTime(r.started_at)} by ${r.started_by}` },
        ]} />
      )}
      {detail.data && (
        <Card title={`${detail.data.run_ref} — ${formatDate(detail.data.reporting_date)}`} actions={
          <div className="inline-actions">
            {detail.data.state === "FAILED" && hasPermission("REPORT_GENERATE") && (
              <button className="btn btn-primary btn-small" disabled={act.busy} onClick={() => void call(`/v1/runs/${detail.data!.run_id}/resume`, (r) => `Resumed: ${r.state}.`)}>Resume</button>
            )}
            {detail.data.state === "READY_FOR_REVIEW" && hasPermission("REPORT_APPROVE") && (
              <button className="btn btn-primary btn-small" disabled={act.busy} onClick={() => void call(`/v1/runs/${detail.data!.run_id}/approve`, () => "Run approved by HR.")}>Approve run</button>
            )}
            {["APPROVED", "DELIVERY_FAILED"].includes(detail.data.state) && hasPermission("REPORT_APPROVE") && (
              <button className="btn btn-primary btn-small" disabled={act.busy} onClick={() => void call(`/v1/runs/${detail.data!.run_id}/distribute`,
                (r) => `Distribution (${r.mode}): ${r.sent} sent, ${r.failed} failed${(r.problems as string[])?.length ? ` — ${(r.problems as string[]).join("; ")}` : ""}.`)}>Distribute approved reports</button>
            )}
            <Link className="btn btn-ghost btn-small" to="/report-preview">Reports</Link>
          </div>
        }>
          {detail.data.error && <Notice kind="fail">{detail.data.error}</Notice>}
          {detail.data.stats.kpis && (
            <div className="kpi-grid">
              <KpiCard label="Eligible" value={detail.data.stats.kpis.eligible_employees} />
              <KpiCard label="Pending review" value={detail.data.stats.kpis.pending_review} />
              <KpiCard label="Exceptions" value={detail.data.stats.reconciliation?.exceptions ?? 0} />
              <KpiCard label="Missing datasets" value={detail.data.stats.missing_datasets?.length ?? 0} />
            </div>
          )}
          <DataTable rows={detail.data.logs} rowKey={(l) => `${l.stage}-${l.started_at}`} columns={[
            { header: "Stage", render: (l) => l.stage }, { header: "Outcome", render: (l) => <StatusBadge value={l.outcome} /> },
            { header: "Duration", render: (l) => (l.duration_ms !== null ? `${l.duration_ms} ms` : "") },
            { header: "Records", render: (l) => l.record_count ?? "" }, { header: "Message", render: (l) => l.message ?? "" }]} />
        </Card>
      )}
    </>
  );
}

// ------------------------------------------------------------------ Mapping & organisation
export function EmployeeMappingPage() {
  const [status, setStatus] = useState("");
  return (
    <>
      <PageHeader title="Employee Mapping" subtitle="Cross-system identities: approved mapping → exact code → manual review" />
      <Toolbar>
        <Field label="Status">
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">All</option><option value="VERIFIED">Verified</option><option value="PENDING">Pending</option><option value="REJECTED">Rejected</option>
          </select>
        </Field>
      </Toolbar>
      <MappingTable key={status} status={status} />
    </>
  );
}

export function DepartmentMappingPage() {
  const depts = useApi<{ department_code: string; department_name: string; parent: string | null; hod_employee_code: string | null; is_active: boolean }[]>("/v1/departments");
  const emps = useApi<EmployeeRow[]>("/v1/employees");
  return (
    <>
      <PageHeader title="Department Mapping" subtitle="From the latest Department Master and Employee Master uploads" />
      {depts.error && <ErrorNotice error={depts.error} />}
      {depts.data && (depts.data.length ? (
        <DataTable rows={depts.data} rowKey={(d) => d.department_code} columns={[
          { header: "Code", render: (d) => <strong>{d.department_code}</strong> }, { header: "Name", render: (d) => d.department_name },
          { header: "Parent", render: (d) => d.parent ?? "" }, { header: "HOD", render: (d) => d.hod_employee_code ?? "" },
          { header: "Employees", render: (d) => emps.data?.filter((e) => e.department_code === d.department_code).length ?? "" },
          { header: "Active", render: (d) => (d.is_active ? "Yes" : "No") }]} />
      ) : <Notice>No Department Master uploaded yet.</Notice>)}
      {emps.data && (
        <Card title="Employees (first 200)">
          <DataTable rows={emps.data} rowKey={(e) => String(e.employee_key)} columns={[
            { header: "Code", render: (e) => e.employee_code }, { header: "Name", render: (e) => e.employee_name ?? "" },
            { header: "Department", render: (e) => e.department_code ?? "" }, { header: "Location", render: (e) => e.location_code ?? "" },
            { header: "Joined", render: (e) => (e.joining_date ? formatDate(e.joining_date) : "") },
            { header: "Exit", render: (e) => (e.exit_date ? formatDate(e.exit_date) : "") }]} />
        </Card>
      )}
    </>
  );
}

export function HierarchyPage() {
  const rows = useApi<{ employee_code: string; manager_code: string | null; effective_from: string; effective_to: string | null }[]>("/v1/hierarchy");
  const holidays = useApi<{ date: string; name: string; location_code: string | null }[]>("/v1/holidays");
  return (
    <>
      <PageHeader title="Reporting Hierarchy" subtitle="Effective-dated reporting lines and the holiday calendar" />
      {rows.error && <ErrorNotice error={rows.error} />}
      {rows.data && (rows.data.length ? (
        <DataTable rows={rows.data} rowKey={(r) => `${r.employee_code}-${r.effective_from}`} columns={[
          { header: "Employee", render: (r) => r.employee_code }, { header: "Manager", render: (r) => r.manager_code ?? "" },
          { header: "From", render: (r) => formatDate(r.effective_from) }, { header: "To", render: (r) => (r.effective_to ? formatDate(r.effective_to) : "current") }]} />
      ) : <Notice>No Reporting Hierarchy uploaded yet.</Notice>)}
      {holidays.data && (
        <Card title="Holiday calendar">
          <DataTable rows={holidays.data} rowKey={(h) => `${h.date}-${h.location_code}`} columns={[
            { header: "Date", render: (h) => formatDate(h.date) }, { header: "Holiday", render: (h) => h.name },
            { header: "Location", render: (h) => h.location_code ?? "All" }]} />
        </Card>
      )}
    </>
  );
}

// ------------------------------------------------------------------ Rules & settings
interface Rules {
  rule_version: string; approval_status: string; approved_by: string | null; approved_on: string | null; is_approved: boolean;
  calculation: Record<string, unknown>; unresolved: string[];
  source_authority: { approval_status: string; domains: Record<string, { proposed_source: string | null; authoritative_source: string | null }> };
}

export function AttendanceRulesPage() {
  const rules = useApi<Rules>("/v1/admin/rules");
  return (
    <>
      <PageHeader title="Attendance Rules" subtitle="Changed only by HR decision, via config/attendance_rules.yaml (versioned)" />
      {rules.error && <ErrorNotice error={rules.error} />}
      {rules.data && (
        <>
          <p>Version <Badge>{rules.data.rule_version}</Badge> <StatusBadge value={rules.data.approval_status} />
            {rules.data.approved_by && <span className="muted"> — approved by {rules.data.approved_by} on {rules.data.approved_on}</span>}</p>
          {!rules.data.is_approved && <Notice kind="warn">{rules.data.unresolved.length} decisions are pending; affected results are PROVISIONAL or UNRESOLVED and percentages are withheld.</Notice>}
          <DataTable rows={Object.entries(rules.data.calculation)} rowKey={([k]) => k} columns={[
            { header: "Rule", render: ([k]) => k.replace(/_/g, " ") },
            { header: "Value", render: ([, v]) => (v === null ? <Badge kind="warn">PENDING HR DECISION</Badge> : String(Array.isArray(v) ? v.join(", ") : v)) }]} />
          <Card title={`Source authority — ${rules.data.source_authority.approval_status.replace("_", " ")}`}>
            <DataTable rows={Object.entries(rules.data.source_authority.domains)} rowKey={([k]) => k} columns={[
              { header: "Domain", render: ([k]) => k.replace(/_/g, " ") }, { header: "Proposed", render: ([, v]) => v.proposed_source ?? "—" },
              { header: "Approved", render: ([, v]) => v.authoritative_source ?? <Badge kind="warn">PENDING HR</Badge> }]} />
          </Card>
        </>
      )}
    </>
  );
}

interface AppSettings {
  environment: string; auth_mode: string;
  email: { enabled: boolean; transport: string; sender: string | null; test_recipients: string[]; recipients_approval: string; hod_lists: number; directors: number; hr: number };
  ai: { enabled: boolean; provider: string; model: string | null; timeout_seconds: number };
  uploads: { max_file_size_mb: number; allowed_extensions: string[] };
  session: { idle_timeout_minutes: number; max_failed_logins: number };
}

export function AppSettingsPage() {
  const s = useApi<AppSettings>("/v1/admin/settings");
  const audit = useApi<{ at: string; username: string | null; action: string; outcome: string; detail: string | null }[]>("/v1/admin/audit?limit=100");
  return (
    <>
      <PageHeader title="Application Settings" subtitle="Read-only. Settings change through reviewed configuration files." />
      {s.error && <ErrorNotice error={s.error} />}
      {s.data && (
        <div className="grid-2">
          <Card title="Access and uploads">
            <ul className="kv-list">
              <li><span>Environment</span><strong>{s.data.environment}</strong></li>
              <li><span>Access mode</span><strong>{s.data.auth_mode === "none" ? "No login (localhost only)" : "Sign-in"}</strong></li>
              <li><span>Max upload</span><strong>{s.data.uploads.max_file_size_mb} MB ({s.data.uploads.allowed_extensions.join(", ")})</strong></li>
              <li><span>Idle timeout</span><strong>{s.data.session.idle_timeout_minutes} min</strong></li>
            </ul>
          </Card>
          <Card title="Email and AI">
            <ul className="kv-list">
              <li><span>Email delivery</span><strong>{s.data.email.enabled ? `LIVE via ${s.data.email.transport}` : "Test mode (outbox only)"}</strong></li>
              <li><span>Recipient lists</span><StatusBadge value={s.data.email.recipients_approval} /></li>
              <li><span>HOD / Directors / HR lists</span><strong>{s.data.email.hod_lists} / {s.data.email.directors} / {s.data.email.hr}</strong></li>
              <li><span>AI</span><strong>{s.data.ai.enabled ? `${s.data.ai.provider} · ${s.data.ai.model}` : "Disabled"}</strong></li>
            </ul>
          </Card>
        </div>
      )}
      {audit.data && (
        <Card title="Recent user activity (audit)">
          <DataTable rows={audit.data} rowKey={(a) => `${a.at}-${a.action}-${a.username}`} columns={[
            { header: "When", render: (a) => formatDateTime(a.at) }, { header: "User", render: (a) => a.username ?? "" },
            { header: "Action", render: (a) => a.action }, { header: "Outcome", render: (a) => <StatusBadge value={a.outcome} /> },
            { header: "Detail", render: (a) => <code className="small">{(a.detail ?? "").slice(0, 160)}</code> }]} />
        </Card>
      )}
    </>
  );
}

export function AppLogsPage() {
  const logs = useApi<{ lines: string[] }>("/v1/system/logs?lines=300");
  return (
    <>
      <PageHeader title="Application Logs" subtitle="Latest 300 structured log lines (secrets redacted at source)" />
      <Toolbar><button className="btn btn-ghost btn-inline" onClick={logs.reload}>Refresh</button></Toolbar>
      {logs.error && <ErrorNotice error={logs.error} />}
      {logs.data && <pre className="log-view">{[...logs.data.lines].reverse().join("\n") || "No log lines yet."}</pre>}
    </>
  );
}
