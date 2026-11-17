import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { apiUrl } from "../api/client";
import { useApi, withQuery } from "../api/useApi";
import type { AttendanceReport, EmployeeList, EmployeeReport, ReportDay, Tally } from "../api/types";
import { STATUS_COLORS, STATUS_LABELS } from "../components/charts";
import { Card, DataTable, ErrorNotice, Field, KpiCard, Loading, Notice, PageHeader, Toolbar } from "../components/ui";
import { formatDate, formatHours, formatMinutes, formatTime } from "../format";

const FILTER_KEYS = ["from", "to", "hod", "department", "team", "manager", "category", "status", "q"] as const;
const STATUS_OPTIONS: [string, string][] = [["", "Any status"], ["ABSENT", "Absent"], ["LATE", "Late"], ["MISSING_PUNCH", "Missing punch"],
  ["LEAVE", "Leave"], ["HALF_DAY", "Half day"], ["ON_DUTY", "On duty"], ["WEEK_OFF", "Week off"], ["NOT_TRACKED", "Not tracked"], ["PRESENT", "Present"]];

const pctText = (v: number | null) => (v === null ? "—" : `${v}%`);

function StatusPill({ status, label }: { status: string; label: string }) {
  const c = STATUS_COLORS[status] ?? "#6e6152";
  return <span className="st" style={{ background: `${c}22`, color: c }}>{label}</span>;
}

function TallyKpis({ t, extra }: { t: Tally; extra?: [string, string | number][] }) {
  return (
    <div className="kpi-grid">
      {extra?.map(([l, v]) => <KpiCard key={l} label={l} value={v} />)}
      <KpiCard label="Attendance" value={pctText(t.attendance_pct)} />
      <KpiCard label="Present" value={t.present} />
      <KpiCard label="Absent" value={t.absent} />
      <KpiCard label="Leave" value={t.leave + t.half_day} />
      <KpiCard label="Late" value={t.late} />
      <KpiCard label="Missing punch" value={t.missing_punch} />
      <KpiCard label="Week off" value={t.week_off} />
      <KpiCard label="Not tracked" value={t.not_tracked} />
      <KpiCard label="Avg arrival" value={t.avg_in_time ?? "—"} />
      <KpiCard label="Avg hours (h:mm)" value={formatHours(t.avg_work_hours) || "—"} />
    </div>
  );
}

function dayColumns(withPerson: boolean) {
  return [
    { header: "Date", render: (d: ReportDay) => formatDate(d.date) },
    ...(withPerson ? [
      { header: "Code", render: (d: ReportDay) => d.code },
      { header: "Name", render: (d: ReportDay) => <Link className="link" to={`/employee-report?code=${encodeURIComponent(d.code)}`}>{d.name}</Link> },
      { header: "Department", render: (d: ReportDay) => d.department },
      { header: "HOD", render: (d: ReportDay) => d.hod },
    ] : []),
    { header: "Status", render: (d: ReportDay) => <StatusPill status={d.status} label={d.status_label} /> },
    { header: "In", render: (d: ReportDay) => formatTime(d.in_time) },
    { header: "Out", render: (d: ReportDay) => formatTime(d.out_time) },
    { header: "Hours", render: (d: ReportDay) => formatHours(d.work_hours) },
    { header: "Late", render: (d: ReportDay) => (d.late_minutes ? `${formatMinutes(d.late_minutes)} hrs` : "") },
    { header: "Leave", render: (d: ReportDay) => d.leave_type ?? "" },
    { header: "Permission", render: (d: ReportDay) => d.permission },
  ];
}

// ---------------------------------------------------------------------------- filtered report
export function ReportsPage() {
  const [params, setParams] = useSearchParams();
  const [view, setView] = useState<"people" | "days">("people");
  const [copied, setCopied] = useState(false);
  const filters = Object.fromEntries(FILTER_KEYS.map((k) => [k, params.get(k) ?? ""])) as Record<(typeof FILTER_KEYS)[number], string>;
  const report = useApi<AttendanceReport>(withQuery("/v1/reports/attendance", { ...filters, days: view === "days" ? "true" : "" }));
  const set = (k: string, v: string) => {
    const next = new URLSearchParams(params);
    if (v) next.set(k, v); else next.delete(k);
    if (k === "hod") next.delete("team");
    setParams(next, { replace: true });
  };
  const data = report.data;
  const from = filters.from || data?.from || "";
  const to = filters.to || data?.to || "";
  const anyFilter = FILTER_KEYS.some((k) => k !== "from" && k !== "to" && filters[k]);

  function select(label: string, key: "hod" | "department" | "team" | "manager" | "category") {
    const opts = data?.options[key] ?? [];
    return (
      <Field label={label}>
        <select value={filters[key]} onChange={(e) => set(key, e.target.value)}>
          <option value="">All</option>
          {[...new Set([...opts, ...(filters[key] ? [filters[key]] : [])])].map((o) => <option key={o} value={o}>{o}</option>)}
        </select>
      </Field>
    );
  }

  async function copyLink() {
    await navigator.clipboard?.writeText(window.location.href);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 2000);
  }

  return (
    <>
      <PageHeader title="Attendance report" subtitle="Any date range, filtered by HOD, department, team, manager or status. Share the link or download Excel." />
      <Card>
        <div className="filter-grid">
          <Field label="From"><input type="date" value={from} onChange={(e) => set("from", e.target.value)} /></Field>
          <Field label="To"><input type="date" value={to} onChange={(e) => set("to", e.target.value)} /></Field>
          {select("HOD", "hod")}
          {select("Department", "department")}
          {select("Team", "team")}
          {select("Reporting manager", "manager")}
          {select("Category", "category")}
          <Field label="Status (at least once)">
            <select value={filters.status} onChange={(e) => set("status", e.target.value)}>
              {STATUS_OPTIONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </Field>
          <Field label="Search"><input placeholder="Code, name, team, manager…" value={filters.q} onChange={(e) => set("q", e.target.value)} /></Field>
        </div>
        <div className="form-actions">
          {anyFilter && <button className="btn btn-ghost btn-small" onClick={() => setParams(new URLSearchParams(filters.from ? { from, to } : {}), { replace: true })}>Clear filters</button>}
          <a className="btn btn-primary btn-small" href={apiUrl("/v1/reports/attendance/excel", filters)}>Download Excel</a>
          <button className="btn btn-ghost btn-small" onClick={() => void copyLink()}>{copied ? "Link copied" : "Copy link to this report"}</button>
        </div>
      </Card>

      {report.error && <ErrorNotice error={report.error} />}
      {report.loading && !data && <Loading />}
      {data && (
        <>
          {data.dates.length === 0 && <Notice>No uploaded days between {formatDate(data.from)} and {formatDate(data.to)}.</Notice>}
          <TallyKpis t={data.totals} extra={[["Employees", data.totals.employees], ["Uploaded days", data.dates.length]]} />
          <Card title={view === "people" ? "By employee" : "Day by day"} actions={
            <div className="chips">
              <button className={`chip${view === "people" ? " on" : ""}`} onClick={() => setView("people")}>By employee</button>
              <button className={`chip${view === "days" ? " on" : ""}`} onClick={() => setView("days")}>Day by day</button>
            </div>}>
            {view === "people" ? (
              <DataTable rows={data.employees.slice(0, 2000)} rowKey={(p) => p.code} columns={[
                { header: "Code", render: (p) => p.code },
                { header: "Name", render: (p) => <Link className="link" to={withQuery("/employee-report", { code: p.code, from, to })}>{p.name}</Link> },
                { header: "Department", render: (p) => p.department },
                { header: "HOD", render: (p) => p.hod },
                { header: "Team", render: (p) => p.team },
                { header: "Days", render: (p) => p.days },
                { header: "Present", render: (p) => p.present },
                { header: "Absent", render: (p) => p.absent },
                { header: "Missing punch", render: (p) => p.missing_punch },
                { header: "Leave", render: (p) => p.leave + p.half_day },
                { header: "Late", render: (p) => p.late },
                { header: "Week off", render: (p) => p.week_off },
                { header: "Attendance", render: (p) => pctText(p.attendance_pct) },
              ]} />
            ) : (
              <>
                {data.days_truncated && <Notice kind="warn">Showing the first 5,000 rows; the Excel download has all of them.</Notice>}
                <DataTable rows={(data.days ?? []).slice(0, 5000)} rowKey={(d) => `${d.date}-${d.code}`} columns={dayColumns(true)} />
              </>
            )}
          </Card>
        </>
      )}
    </>
  );
}

// ---------------------------------------------------------------------------- one employee
export function EmployeeReportPage() {
  const [params, setParams] = useSearchParams();
  const code = params.get("code") ?? "";
  const [typed, setTyped] = useState(code);
  const list = useApi<EmployeeList>("/v1/employees");
  const report = useApi<EmployeeReport>(code ? withQuery(`/v1/reports/employee/${encodeURIComponent(code)}`, { from: params.get("from"), to: params.get("to") }) : null);
  const byLabel = useMemo(() => new Map((list.data?.employees ?? []).map((e) => [`${e.code} — ${e.name}`, e.code])), [list.data]);
  const set = (k: string, v: string) => {
    const next = new URLSearchParams(params);
    if (v) next.set(k, v); else next.delete(k);
    setParams(next, { replace: true });
  };
  function choose(value: string) {
    setTyped(value);
    const picked = byLabel.get(value);
    if (picked) set("code", picked);
  }
  const data = report.data;
  const from = params.get("from") || data?.from || "";
  const to = params.get("to") || data?.to || "";

  return (
    <>
      <PageHeader title="Employee report" subtitle="Day-by-day attendance of one employee (Pocket HRMS)" />
      <Toolbar>
        <Field label="Employee">
          <input list="dl-emp" value={typed} placeholder="Type a code or name" onChange={(e) => choose(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && set("code", byLabel.get(typed) ?? typed.trim().toUpperCase())} />
          <datalist id="dl-emp">{[...byLabel.keys()].map((l) => <option key={l} value={l} />)}</datalist>
        </Field>
        <Field label="From"><input type="date" value={from} onChange={(e) => set("from", e.target.value)} /></Field>
        <Field label="To"><input type="date" value={to} onChange={(e) => set("to", e.target.value)} /></Field>
        {code && data && (
          <div className="toolbar-actions">
            <a className="btn btn-primary btn-inline" href={apiUrl(`/v1/reports/employee/${encodeURIComponent(code)}/excel`, { from, to })}>Download Excel</a>
          </div>
        )}
      </Toolbar>
      {!code && <Notice>Choose an employee (code or name). You can also open this from the Employees screen or by clicking a name in Insights.</Notice>}
      {report.error && <ErrorNotice error={report.error} />}
      {report.loading && <Loading />}
      {data && (
        <>
          <Card title={`${data.employee.name} (${data.employee.code})`}>
            <p className="muted">
              {[data.employee.department, data.employee.hod_name && `HOD ${data.employee.hod_name}`, data.employee.team && `Team ${data.employee.team}`,
                data.employee.reporting_manager && `Manager ${data.employee.reporting_manager}`].filter(Boolean).join(" · ") || "—"}
              {data.employee.status === "LEFT" && " · Left"}
            </p>
            {!data.in_master && <Notice kind="warn">Not in the employee master. Add them on the Employees screen so their HOD receives them.</Notice>}
            <div className="day-strip" aria-label="Status per day">
              {data.days.map((d) => (
                <span key={d.date} className="day-cell" style={{ background: STATUS_COLORS[d.status] }} title={`${formatDate(d.date)}: ${d.status_label}`}>
                  {d.date.slice(8, 10)}
                </span>
              ))}
            </div>
            <div className="legend small">
              {Object.entries(STATUS_LABELS).map(([k, l]) => <span key={k}><i style={{ background: STATUS_COLORS[k] }} /> {l}</span>)}
            </div>
          </Card>
          <TallyKpis t={data.summary} extra={[["Days in range", data.summary.days]]} />
          <Card title="Day by day">
            {data.days.length === 0 ? <p className="muted">No attendance in this range.</p> : <DataTable rows={data.days} rowKey={(d) => d.date} columns={dayColumns(false)} />}
          </Card>
        </>
      )}
    </>
  );
}
