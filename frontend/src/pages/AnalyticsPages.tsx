import { useState, type FormEvent, type ReactNode } from "react";
import { istIso, shiftIso, useDefaultDate } from "../api/dates";
import { useApi, withQuery } from "../api/useApi";
import type { AttendanceSummary, FactRow, TrendPoint } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { LineChart, StackedBars, STATUS_COLORS, STATUS_LABELS, STATUS_ORDER } from "../components/charts";
import { Card, DataTable, ErrorNotice, Field, KpiCard, Loading, Notice, PageHeader, StatusBadge, Toolbar, pct } from "../components/ui";
import { formatDate } from "../format";

function FactTable({ rows, showDate = false }: { rows: FactRow[]; showDate?: boolean }) {
  return (
    <DataTable rows={rows} rowKey={(r) => `${r.employee_code}-${r.date}`} columns={[
      ...(showDate ? [{ header: "Date", render: (r: FactRow) => formatDate(r.date) }] : []),
      { header: "Employee", render: (r) => <><strong>{r.employee_code}</strong><div className="muted small">{r.employee_name}</div></> },
      { header: "Dept", render: (r) => r.department_code ?? "" },
      { header: "Status", render: (r) => <StatusBadge value={r.status} /> },
      { header: "Bizom", render: (r) => r.bizom_status ?? "" },
      { header: "Pocket HRMS", render: (r) => r.hrms_status ?? "" },
      { header: "Leave", render: (r) => r.leave_status ?? "" },
      { header: "In", render: (r) => r.first_in ?? "" },
      { header: "Out", render: (r) => r.last_out ?? "" },
      { header: "Punches", render: (r) => r.punch_count },
      { header: "Reason", render: (r) => <span className="small">{r.reason}</span> },
    ]} />
  );
}

function RangeBar({ start, end, setStart, setEnd, children }: { start: string; end: string; setStart: (v: string) => void; setEnd: (v: string) => void; children?: ReactNode }) {
  return (
    <Toolbar>
      <Field label="From"><input type="date" value={start} onChange={(e) => setStart(e.target.value)} /></Field>
      <Field label="To"><input type="date" value={end} onChange={(e) => setEnd(e.target.value)} /></Field>
      {children}
    </Toolbar>
  );
}

function useRange(days = 29) {
  const [end, setEnd] = useState(istIso(-1));
  const [start, setStart] = useState(shiftIso(istIso(-1), -days));
  return { start, end, setStart, setEnd };
}

// ------------------------------------------------------------------ Daily Attendance
export function DailyAttendancePage() {
  const [day, setDay] = useDefaultDate();
  const [status, setStatus] = useState("");
  const { hasPermission } = useAuth();
  const summary = useApi<AttendanceSummary>(day ? withQuery("/v1/attendance/summary", { date: day }) : null);
  const rows = useApi<FactRow[]>(day && hasPermission("ATTENDANCE_VIEW_EMPLOYEE") ? withQuery("/v1/attendance/daily", { date: day, status }) : null);
  const k = summary.data?.kpis;
  return (
    <>
      <PageHeader title="Daily Attendance" subtitle={summary.data?.run ? `Run ${summary.data.run.run_ref}` : undefined} />
      <Toolbar>
        <Field label="Date"><input type="date" value={day} onChange={(e) => setDay(e.target.value)} /></Field>
        {hasPermission("ATTENDANCE_VIEW_EMPLOYEE") && (
          <Field label="Status">
            <select value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">All statuses</option>
              {STATUS_ORDER.map((s) => <option key={s} value={s}>{STATUS_LABELS[s]}</option>)}
            </select>
          </Field>
        )}
      </Toolbar>
      {summary.error && <ErrorNotice error={summary.error} />}
      {summary.data && !summary.data.run && <Notice>No processed attendance for {formatDate(day)}.</Notice>}
      {k && (
        <div className="kpi-grid">
          <KpiCard label="Eligible" value={k.eligible_employees} />
          {STATUS_ORDER.filter((s) => k.counts[s]).map((s) => <KpiCard key={s} label={STATUS_LABELS[s]} value={k.counts[s]} />)}
          <KpiCard label="Attendance %" value={<span className="kpi-small">{pct(k.attendance_pct)}</span>} />
        </div>
      )}
      {rows.loading && <Loading />}
      {rows.data && <FactTable rows={rows.data} />}
    </>
  );
}

// ------------------------------------------------------------------ Employee Attendance
interface History { employee_code: string; employee_name: string | null; rows: FactRow[]; summary: Record<string, number>; exceptions: { exception_id: number; date: string; category: string; status: string }[] }

export function EmployeeAttendancePage() {
  const r = useRange();
  const [code, setCode] = useState("");
  const [query, setQuery] = useState<string | null>(null);
  const hist = useApi<History>(query ? withQuery(`/v1/attendance/employee/${encodeURIComponent(query)}`, { start: r.start, end: r.end }) : null);
  function submit(e: FormEvent) {
    e.preventDefault();
    setQuery(code.trim() || null);
  }
  return (
    <>
      <PageHeader title="Employee Attendance" subtitle="History, punches, leave and exceptions for one employee" />
      <form onSubmit={submit}>
        <RangeBar {...r}>
          <Field label="Employee code"><input value={code} onChange={(e) => setCode(e.target.value)} placeholder="e.g. E1023" /></Field>
          <button className="btn btn-primary btn-inline">Show</button>
        </RangeBar>
      </form>
      {hist.loading && <Loading />}
      {hist.error && <ErrorNotice error={hist.error} />}
      {hist.data && (
        <>
          <h2>{hist.data.employee_code} {hist.data.employee_name}</h2>
          <div className="kpi-grid">
            {Object.entries(hist.data.summary).map(([s, n]) => <KpiCard key={s} label={STATUS_LABELS[s] ?? s} value={n} />)}
          </div>
          <FactTable rows={hist.data.rows} showDate />
          {hist.data.exceptions.length > 0 && (
            <Card title="Exceptions">
              <DataTable rows={hist.data.exceptions} rowKey={(x) => String(x.exception_id)} columns={[
                { header: "#", render: (x) => x.exception_id }, { header: "Date", render: (x) => formatDate(x.date) },
                { header: "Category", render: (x) => <StatusBadge value={x.category} /> }, { header: "Status", render: (x) => <StatusBadge value={x.status} /> }]} />
            </Card>
          )}
        </>
      )}
    </>
  );
}

// ------------------------------------------------------------------ Department Analytics
export function DepartmentAnalyticsPage() {
  const [day, setDay] = useDefaultDate();
  const r = useRange();
  const [dept, setDept] = useState("");
  const summary = useApi<AttendanceSummary>(day ? withQuery("/v1/attendance/summary", { date: day }) : null);
  const trend = useApi<TrendPoint[]>(withQuery("/v1/attendance/trend", { start: r.start, end: r.end, department: dept }));
  const depts = summary.data?.departments ?? [];
  return (
    <>
      <PageHeader title="Department Analytics" subtitle="Department comparison and trends" />
      <Toolbar><Field label="Comparison date"><input type="date" value={day} onChange={(e) => setDay(e.target.value)} /></Field></Toolbar>
      {summary.error && <ErrorNotice error={summary.error} />}
      <Card title={`Department comparison — ${formatDate(day)}`}>
        <StackedBars title="Attendance status by department" rows={depts.map((d) => ({ label: `${d.department_code}`, counts: d.counts }))} />
        <DataTable rows={depts} rowKey={(d) => d.department_code} columns={[
          { header: "Department", render: (d) => `${d.department_code} — ${d.department_name}` },
          { header: "Eligible", render: (d) => d.eligible }, { header: "Present", render: (d) => d.counts.PRESENT ?? 0 },
          { header: "Absent", render: (d) => d.counts.ABSENT ?? 0 }, { header: "Leave", render: (d) => d.counts.APPROVED_LEAVE ?? 0 },
          { header: "Unresolved", render: (d) => d.counts.UNRESOLVED ?? 0 },
          { header: "Attendance %", render: (d) => pct(d.attendance_pct) }, { header: "Absenteeism %", render: (d) => pct(d.absenteeism_pct) }]} />
      </Card>
      <Card title="Trend">
        <RangeBar {...r}>
          <Field label="Department">
            <select value={dept} onChange={(e) => setDept(e.target.value)}>
              <option value="">All in scope</option>
              {depts.map((d) => <option key={d.department_code} value={d.department_code}>{d.department_code}</option>)}
            </select>
          </Field>
        </RangeBar>
        {trend.error && <ErrorNotice error={trend.error} />}
        {trend.data && (
          <LineChart title="Daily status counts" labels={trend.data.map((t) => formatDate(t.date).slice(0, 6))} series={[
            { name: "Present", color: STATUS_COLORS.PRESENT, values: trend.data.map((t) => t.counts.PRESENT ?? 0) },
            { name: "Absent", color: STATUS_COLORS.ABSENT, values: trend.data.map((t) => t.counts.ABSENT ?? 0) },
            { name: "Leave", color: STATUS_COLORS.APPROVED_LEAVE, values: trend.data.map((t) => t.counts.APPROVED_LEAVE ?? 0) },
          ]} />
        )}
      </Card>
    </>
  );
}

// ------------------------------------------------------------------ Absenteeism
export function AbsenteeismPage() {
  const r = useRange();
  const trend = useApi<TrendPoint[]>(withQuery("/v1/attendance/trend", { start: r.start, end: r.end }));
  const pctKnown = trend.data?.some((t) => t.absenteeism_pct !== null);
  return (
    <>
      <PageHeader title="Absenteeism" subtitle="Absences over time" />
      <RangeBar {...r} />
      {trend.error && <ErrorNotice error={trend.error} />}
      {!pctKnown && trend.data && trend.data.length > 0 && <Notice kind="warn">Absenteeism % is shown once HR approves the attendance rules; counts are shown meanwhile.</Notice>}
      {trend.data && (
        <>
          <LineChart title={pctKnown ? "Absenteeism %" : "Absent employees per day"} unit={pctKnown ? "%" : ""}
            labels={trend.data.map((t) => formatDate(t.date).slice(0, 6))}
            series={[{ name: pctKnown ? "Absenteeism %" : "Absent", color: STATUS_COLORS.ABSENT,
              values: trend.data.map((t) => (pctKnown ? t.absenteeism_pct : t.counts.ABSENT ?? 0)) }]} />
          <DataTable rows={[...trend.data].reverse()} rowKey={(t) => t.date} columns={[
            { header: "Date", render: (t) => formatDate(t.date) }, { header: "Eligible", render: (t) => t.eligible },
            { header: "Absent", render: (t) => t.counts.ABSENT ?? 0 }, { header: "Absenteeism %", render: (t) => pct(t.absenteeism_pct) }]} />
        </>
      )}
    </>
  );
}

// ------------------------------------------------------------------ Leave Analytics
export function LeaveAnalyticsPage() {
  const r = useRange();
  const trend = useApi<TrendPoint[]>(withQuery("/v1/attendance/trend", { start: r.start, end: r.end }));
  const totals = (trend.data ?? []).reduce((acc, t) => {
    for (const s of ["APPROVED_LEAVE", "HALF_DAY", "PENDING_APPROVAL"]) acc[s] = (acc[s] ?? 0) + (t.counts[s] ?? 0);
    return acc;
  }, {} as Record<string, number>);
  return (
    <>
      <PageHeader title="Leave Analytics" subtitle="Approved, half-day and pending leave (only approved leave counts as leave)" />
      <RangeBar {...r} />
      {trend.error && <ErrorNotice error={trend.error} />}
      {trend.data && (
        <>
          <div className="kpi-grid">
            <KpiCard label="Approved leave days" value={totals.APPROVED_LEAVE ?? 0} />
            <KpiCard label="Half days" value={totals.HALF_DAY ?? 0} />
            <KpiCard label="Pending approval" value={totals.PENDING_APPROVAL ?? 0} />
          </div>
          <LineChart title="Leave per day" labels={trend.data.map((t) => formatDate(t.date).slice(0, 6))} series={[
            { name: "Approved leave", color: STATUS_COLORS.APPROVED_LEAVE, values: trend.data.map((t) => t.counts.APPROVED_LEAVE ?? 0) },
            { name: "Half day", color: STATUS_COLORS.HALF_DAY, values: trend.data.map((t) => t.counts.HALF_DAY ?? 0) },
            { name: "Pending", color: STATUS_COLORS.PENDING_APPROVAL, values: trend.data.map((t) => t.counts.PENDING_APPROVAL ?? 0) },
          ]} />
        </>
      )}
    </>
  );
}

// ------------------------------------------------------------------ Missing Punches
export function MissingPunchesPage() {
  const [day, setDay] = useDefaultDate();
  const rows = useApi<FactRow[]>(day ? withQuery("/v1/attendance/daily", { date: day, status: "MISSING_PUNCH" }) : null);
  return (
    <>
      <PageHeader title="Missing Punches" subtitle="Employees with an incomplete punch sequence" />
      <Toolbar><Field label="Date"><input type="date" value={day} onChange={(e) => setDay(e.target.value)} /></Field></Toolbar>
      {rows.loading && <Loading />}
      {rows.error && <ErrorNotice error={rows.error} />}
      {rows.data && <FactTable rows={rows.data} />}
    </>
  );
}
