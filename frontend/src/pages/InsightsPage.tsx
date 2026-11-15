import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, apiUrl } from "../api/client";
import { useAction, useApi } from "../api/useApi";
import type { BreakdownRow, DayDetail, DayListItem, EmailResult, EmployeeRow, Highlight, Insights } from "../api/types";
import { SOURCE_LABELS, scopeLabel } from "../api/types";
import { Link } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { HBars, LineChart, STATUS_COLORS, STATUS_LABELS } from "../components/charts";
import { ActionMessages, Card, DataTable, ErrorNotice, Field, KpiCard, Loading, Notice, PageHeader, StatusBadge, Toolbar } from "../components/ui";
import { formatDate } from "../format";

export function HighlightList({ items }: { items: Highlight[] }) {
  return (
    <ul className="hl-list">
      {items.map((h, i) => <li key={i} className={`hl hl-${h.kind}`}>{h.text}</li>)}
    </ul>
  );
}

const FILTERS: [string, string][] = [["ALL", "All"], ["ABSENT", "Absent"], ["LATE", "Late"], ["MISSING_PUNCH", "Missing punch"],
  ["LEFT_EARLY", "Left early"], ["LEAVE", "Leave / on duty / week off"], ["SHORT_HOURS", "Short hours"], ["NOT_TRACKED", "Not tracked"],
  ["BIZOM", "From Bizom"]];

function inScope(r: EmployeeRow, scope: string): boolean {
  if (scope === "ALL") return true;
  if (scope.startsWith("HOD:")) return r.hod === scope.slice(4);
  return r.category === scope;
}

/** Breakdown table for a scope; older days (before the employee master) fall back to categories. */
function breakdownOf(ins: Insights, scope: string): { by: string; rows: BreakdownRow[] } {
  const saved = ins.scopes[scope]?.breakdown;
  if (saved) return saved;
  if (scope !== "ALL" || ins.categories.length < 2) return { by: "Category", rows: [] };
  return { by: "Category", rows: Object.entries(ins.by_category).map(([name, c]) => ({
    name, hod: null, employees: c.employees, tracked: c.tracked, attendance_pct: c.attendance_pct,
    present: c.counts.PRESENT + c.counts.ON_DUTY + c.counts.MISSING_PUNCH, absent: c.counts.ABSENT, late: c.late,
    leave: c.counts.LEAVE + c.counts.HALF_DAY, not_tracked: c.counts.NOT_TRACKED })) };
}

const pctColor = (v: number) => (v < 75 ? "#a52a1a" : v < 90 ? "#c88a00" : "#2e7d4f");

function matches(r: EmployeeRow, f: string): boolean {
  if (f === "ALL") return true;
  if (f === "LEAVE") return ["LEAVE", "HALF_DAY", "ON_DUTY", "WEEK_OFF"].includes(r.status);
  if (f === "BIZOM") return r.source === "BIZOM";
  if (["LATE", "LEFT_EARLY", "SHORT_HOURS"].includes(f)) return r.flags.includes(f);
  return r.status === f;
}

export function InsightsPage() {
  const [params, setParams] = useSearchParams();
  const days = useApi<DayListItem[]>("/v1/days");
  const date = params.get("date") || days.data?.[0]?.report_date || "";
  const [scope, setScope] = useState("ALL");
  const [filter, setFilter] = useState("ALL");
  const [search, setSearch] = useState("");
  const [dept, setDept] = useState("");
  const [preview, setPreview] = useState(false);
  const day = useApi<DayDetail>(date ? `/v1/days/${date}` : null);
  const send = useAction();
  const { hasPermission } = useAuth();

  useEffect(() => setScope("ALL"), [date]);
  useEffect(() => setDept(""), [scope]);

  const ins = day.data?.insights;
  const data = ins?.scopes[scope];
  const s = data?.summary;
  const rows = useMemo(() => {
    const q = search.trim().toLowerCase();
    return (day.data?.rows ?? []).filter((r) => inScope(r, scope) && matches(r, filter) && (!dept || (r.department || r.category) === dept)
      && (!q || [r.name, r.code, r.team, r.manager].some((v) => (v ?? "").toLowerCase().includes(q))));
  }, [day.data, scope, filter, search, dept]);
  const hasMaster = useMemo(() => (day.data?.rows ?? []).some((r) => r.department || r.hod), [day.data]);
  const deptOptions = useMemo(() => [...new Set((day.data?.rows ?? []).filter((r) => inScope(r, scope))
    .map((r) => r.department || r.category))].sort(), [day.data, scope]);
  const bd = ins ? breakdownOf(ins, scope) : { by: "Category", rows: [] };
  const trend = useMemo(() => [...(days.data ?? [])].reverse().slice(-30), [days.data]);

  async function sendNow() {
    const res = await send.run(() => api.post<{ mode: string; email_results: EmailResult[] }>(`/v1/days/${date}/send`, { scopes: null }),
      (r) => r.email_results.map((e) => `${e.scope_label}: ${e.status === "SAVED" ? "saved (test mode)" : e.status.replace("_", " ").toLowerCase()}`).join(" · "));
    if (res) day.reload();
  }

  if (days.loading) return <Loading />;
  if (days.data && !days.data.length) {
    return (<><PageHeader title="Insights" /><Notice>No day uploaded yet. Start on the Upload page.</Notice></>);
  }

  return (
    <>
      <PageHeader title="Insights" subtitle={date ? `${formatDate(date)} · ${scopeLabel(scope)}` : undefined} />
      <Toolbar>
        <Field label="Day">
          <select value={date} onChange={(e) => setParams({ date: e.target.value })}>
            {days.data?.map((d) => <option key={d.report_date} value={d.report_date}>{formatDate(d.report_date)}</option>)}
          </select>
        </Field>
        <Field label="Report for">
          <select value={scope} onChange={(e) => setScope(e.target.value)}>
            <option value="ALL">All employees</option>
            {ins?.hods && ins.hods.length > 0 && (
              <optgroup label="HOD (their own people)">
                {ins.hods.map((h) => <option key={h.scope} value={h.scope}>{h.name} ({h.employees})</option>)}
              </optgroup>
            )}
            <optgroup label="Pocket HRMS category">
              {ins?.categories.map((c) => <option key={c} value={c}>{c}</option>)}
            </optgroup>
          </select>
        </Field>
        <div className="toolbar-actions">
          <a className="btn btn-ghost btn-inline" href={apiUrl(`/v1/days/${date}/excel`, { scope })}>Excel</a>
          <a className="btn btn-ghost btn-inline" href={apiUrl(`/v1/days/${date}/dashboard`, { scope })}>HTML dashboard</a>
          <button className="btn btn-ghost btn-inline" onClick={() => setPreview(!preview)}>{preview ? "Hide" : "Preview"} email</button>
          {hasPermission("UPLOAD_AND_SEND") && (
            <button className="btn btn-primary btn-inline" disabled={send.busy} onClick={() => void sendNow()}>
              {send.busy ? "Sending…" : "Send emails"}
            </button>
          )}
        </div>
      </Toolbar>
      <ActionMessages error={send.error} message={send.message} />
      {day.error && <ErrorNotice error={day.error} />}
      {day.loading && <Loading />}
      {preview && date && (
        <Card title="Email preview">
          <iframe className="email-frame" sandbox="" title="Email preview" src={apiUrl(`/v1/days/${date}/email-preview`, { scope })} />
        </Card>
      )}
      {s && data && ins && (
        <>
          <div className="kpi-grid">
            <KpiCard label="Attendance" value={s.attendance_pct === null ? "—" : `${s.attendance_pct}%`} />
            <KpiCard label="Employees" value={s.employees} />
            <KpiCard label="Present" value={s.counts.PRESENT} />
            <KpiCard label="Absent" value={s.counts.ABSENT} />
            <KpiCard label="Late" value={s.late} />
            <KpiCard label="Missing punch" value={s.counts.MISSING_PUNCH} />
            <KpiCard label="Leave" value={s.counts.LEAVE + s.counts.HALF_DAY} />
            <KpiCard label="On duty" value={s.counts.ON_DUTY} />
            <KpiCard label="Left early" value={s.left_early} />
            <KpiCard label="Avg arrival" value={s.avg_in_time ?? "—"} />
            <KpiCard label="Avg hours" value={s.avg_work_hours ?? "—"} />
            <KpiCard label="Week off" value={s.counts.WEEK_OFF ?? 0} />
            <KpiCard label="Not tracked" value={s.counts.NOT_TRACKED} />
          </div>
          {day.data && (
            <p className="muted small">
              Files: {day.data.file ? `Pocket HRMS (${day.data.file})` : "Pocket HRMS not uploaded"} · {day.data.bizom_file ? `Bizom (${day.data.bizom_file})` : "Bizom not uploaded"}
            </p>
          )}

          <Card title="Highlights"><HighlightList items={data.highlights} /></Card>

          <div className="grid-2">
            <Card title="Status breakdown">
              <HBars title="Employees by status" bars={(Object.keys(STATUS_LABELS) as (keyof typeof s.counts)[])
                .filter((k) => s.counts[k]).map((k) => ({ label: STATUS_LABELS[k], value: s.counts[k], color: STATUS_COLORS[k] }))} />
            </Card>
            <Card title="Arrival times">
              <HBars title="Employees arriving in each 30-minute window" bars={data.arrivals.map((a) => ({ label: a.label, value: a.count, color: "#d7ad5f" }))} />
            </Card>
            {bd.rows.length > 1 && (
              <Card title={`Attendance by ${bd.by.toLowerCase()}`}>
                <HBars title="Attendance % (tracked employees)" max={100} unit="%" bars={bd.rows
                  .filter((c) => c.attendance_pct !== null)
                  .map((c) => ({ label: c.name, value: c.attendance_pct as number, color: pctColor(c.attendance_pct as number) }))} />
              </Card>
            )}
            {scope === "ALL" && (
              <Card title="Attendance trend">
                <LineChart title="Attendance % per uploaded day" unit="%" labels={trend.map((t) => formatDate(t.report_date).slice(0, 6))}
                  values={trend.map((t) => t.attendance_pct)} />
              </Card>
            )}
          </div>

          {bd.rows.length > 1 && (
            <Card title={`By ${bd.by.toLowerCase()}`}>
              <DataTable rows={bd.rows} rowKey={(x) => x.name} columns={[
                { header: bd.by, render: (x) => <strong>{x.name}</strong> },
                ...(bd.rows.some((x) => x.hod) ? [{ header: "HOD", render: (x: BreakdownRow) => x.hod ?? "" }] : []),
                { header: "Employees", render: (x) => x.employees },
                { header: "Attendance", render: (x) => (x.attendance_pct === null ? "—" : `${x.attendance_pct}%`) },
                { header: "Present", render: (x) => x.present },
                { header: "Absent", render: (x) => x.absent },
                { header: "Late", render: (x) => x.late },
                { header: "Leave", render: (x) => x.leave },
                { header: "Not tracked", render: (x) => x.not_tracked },
              ]} />
            </Card>
          )}

          {scope === "ALL" && ins.hods && ins.hods.length > 0 && (
            <Card title="By HOD">
              <DataTable rows={ins.hods} rowKey={(h) => h.scope} columns={[
                { header: "HOD", render: (h) => <button className="link" onClick={() => setScope(h.scope)}>{h.name}</button> },
                { header: "Departments", render: (h) => h.departments.join(", ") },
                { header: "Employees", render: (h) => h.employees },
                { header: "Attendance", render: (h) => (h.attendance_pct === null ? "—" : `${h.attendance_pct}%`) },
                { header: "Absent", render: (h) => ins.scopes[h.scope]?.summary.counts.ABSENT ?? "" },
                { header: "Late", render: (h) => ins.scopes[h.scope]?.summary.late ?? "" },
              ]} />
            </Card>
          )}

          <Card title="Employees">
            <div className="controls">
              <input className="search" placeholder="Search name, code, team, manager…" value={search} onChange={(e) => setSearch(e.target.value)} aria-label="Search employees" />
              {deptOptions.length > 1 && (
                <select value={dept} onChange={(e) => setDept(e.target.value)} aria-label="Filter by department">
                  <option value="">{hasMaster ? "All departments" : "All categories"}</option>
                  {deptOptions.map((d) => <option key={d} value={d}>{d}</option>)}
                </select>
              )}
              <div className="chips">
                {FILTERS.map(([k, l]) => <button key={k} className={`chip${filter === k ? " on" : ""}`} onClick={() => setFilter(k)}>{l}</button>)}
              </div>
              <span className="muted small">{rows.length} employees</span>
            </div>
            <DataTable rows={rows.slice(0, 1000)} rowKey={(r) => r.code} columns={[
              { header: "Code", render: (r) => r.code },
              { header: "Name", render: (r) => <Link className="link" to={`/employee-report?code=${encodeURIComponent(r.code)}`}>{r.name}</Link> },
              ...(hasMaster ? [
                { header: "Department", render: (r: EmployeeRow) => r.department ?? "" },
                { header: "HOD", render: (r: EmployeeRow) => r.hod ?? "" },
                { header: "Team", render: (r: EmployeeRow) => r.team ?? "" },
                { header: "Manager", render: (r: EmployeeRow) => r.manager ?? "" },
              ] : [{ header: "Category", render: (r: EmployeeRow) => r.category }]),
              { header: "Status", render: (r) => <span className="st" style={{ background: `${STATUS_COLORS[r.status]}22`, color: STATUS_COLORS[r.status] }}>{r.status_label}</span> },
              { header: "In", render: (r) => r.in_time ?? "" },
              { header: "Out", render: (r) => r.out_time ?? "" },
              { header: "Hours", render: (r) => r.work_hours ?? "" },
              { header: "Late", render: (r) => (r.late_minutes ? `${r.late_minutes} min` : "") },
              { header: "Left early", render: (r) => (r.early_minutes ? `${r.early_minutes} min` : "") },
              { header: "Leave", render: (r) => r.leave_type ?? "" },
              { header: "Source", render: (r) => SOURCE_LABELS[r.source ?? "HRMS"] ?? r.source },
            ]} />
          </Card>

          {day.data && day.data.emails.length > 0 && (
            <Card title="Emails for this day">
              <DataTable rows={day.data.emails} rowKey={(e) => `${e.scope}-${e.sent_at}`} columns={[
                { header: "Report", render: (e) => scopeLabel(e.scope) },
                { header: "To", render: (e) => e.recipients },
                { header: "Status", render: (e) => <StatusBadge value={e.status} /> },
                { header: "Mode", render: (e) => e.mode },
                { header: "Note", render: (e) => e.error ?? "" },
              ]} />
            </Card>
          )}
        </>
      )}
    </>
  );
}
