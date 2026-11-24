import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { apiUrl } from "../api/client";
import { useApi } from "../api/useApi";
import type { BreakdownRow, DayDetail, DayListItem, EmployeeRow, Highlight, Insights } from "../api/types";
import { scopeLabel } from "../api/types";
import { Link } from "react-router-dom";
import { HBars, STATUS_COLORS, STATUS_LABELS } from "../components/charts";
import { Card, DataTable, ErrorNotice, Field, KpiCard, Loading, Notice, PageHeader, StatusBadge, Toolbar } from "../components/ui";
import { formatDate, formatHours, formatMinutes, formatTime } from "../format";
import { HO_LEGEND, Person30, Strip30, Trend30, WeekdayHeat, pctColor30, type Pack30 } from "../components/insights30";

interface HoPerson30 { strip: string; pct30: number | null; late30: number; absent30: number; leave30: number; wfh_od30: number; usual_in: string; avg_hours: string }
interface HoPack extends Pack30 { people: Record<string, HoPerson30>; groups: { name: string; pct30: number | null; absent30: number; heat: (number | null)[] }[] }

export function HighlightList({ items }: { items: Highlight[] }) {
  return (
    <ul className="hl-list">
      {items.map((h, i) => <li key={i} className={`hl hl-${h.kind}`}>{h.text}</li>)}
    </ul>
  );
}

const FILTERS: [string, string][] = [["ALL", "All"], ["ABSENT", "Absent"], ["LATE", "Late"], ["MISSING_PUNCH", "Missing punch"],
  ["LEFT_EARLY", "Left early"], ["LEAVE", "Leave / on duty / week off"], ["SHORT_HOURS", "Short hours"], ["NOT_TRACKED", "Not tracked"],
  ["PERMISSION", "Permissions"]];

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

const pctColor = (v: number) => (v < 75 ? "#dc2626" : v < 90 ? "#f59e0b" : "#16a34a");

function matches(r: EmployeeRow, f: string): boolean {
  if (f === "ALL") return true;
  if (f === "LEAVE") return ["LEAVE", "HALF_DAY", "ON_DUTY", "WEEK_OFF", "HOLIDAY"].includes(r.status);
  if (f === "PERMISSION") return !!r.permission;
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
  const day = useApi<DayDetail>(date ? `/v1/days/${date}` : null);
  const pack = useApi<HoPack>(date ? `/v1/days/${date}/pack?scope=${encodeURIComponent(scope)}` : null);
  const [person, setPerson] = useState<EmployeeRow | null>(null);

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
  const pk = pack.data;
  const p30 = (r: EmployeeRow) => pk?.people[r.code.toUpperCase()];

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
          <Link className="btn btn-primary btn-inline" to={`/mail?date=${date}`}>Daily emails</Link>
        </div>
      </Toolbar>
      {day.error && <ErrorNotice error={day.error} />}
      {day.loading && <Loading />}
      {s && data && ins && (
        <>
          <div className="kpi-grid kpi-cols-4">
            <KpiCard label="Attendance" value={s.attendance_pct === null ? "—" : `${s.attendance_pct}%`}
              tone={s.attendance_pct === null ? undefined : s.attendance_pct >= 90 ? "ok" : s.attendance_pct >= 75 ? "warn" : "fail"}
              hint={`of ${s.tracked} tracked · target 90%`} />
            <KpiCard label="Present" value={s.counts.PRESENT} tone="ok"
              hint={[s.late ? `incl. ${s.late} late` : "", s.left_early ? `${s.left_early} left early` : ""].filter(Boolean).join(", ") || "on time"} />
            <KpiCard label="Absent" value={s.counts.ABSENT} tone={s.counts.ABSENT ? "fail" : undefined} hint={s.absent_pct === null ? "" : `${s.absent_pct}% of tracked`} />
            <KpiCard label="Late arrivals" value={s.late} tone={s.late ? "warn" : undefined} hint={s.late ? `avg ${formatMinutes(s.avg_late_minutes)} hrs late` : "nobody late"} />
            <KpiCard label="Missing punch" value={s.counts.MISSING_PUNCH} tone={s.counts.MISSING_PUNCH ? "warn" : undefined} hint="to regularise" />
            <KpiCard label="Leave · On duty · WFH" value={`${s.counts.LEAVE + s.counts.HALF_DAY} · ${s.counts.ON_DUTY} · ${s.counts.WFH ?? 0}`} tone="info" />
            <KpiCard label="Avg arrival · hours" value={s.avg_in_time ?? "—"} tone="brand" hint={`average duty ${formatHours(s.avg_work_hours) || "—"} (h:mm)`} />
            <KpiCard label="Not counted" value={(s.counts.WEEK_OFF ?? 0) + (s.counts.HOLIDAY ?? 0) + s.counts.NOT_TRACKED}
              hint={`${s.employees} employees in total`} />
          </div>
          {day.data && (
            <p className="muted small">
              Files: {day.data.file ? `Pocket HRMS (${day.data.file})` : "Pocket HRMS not uploaded"} · {day.data.permission_file ? `Permission Report (${day.data.permission_file})` : "Permission Report not uploaded"} · {day.data.onduty_file ? `On Duty Report (${day.data.onduty_file})` : "On Duty Report not uploaded"}
            </p>
          )}

          <Card title="Highlights"><HighlightList items={data.highlights} /></Card>

          <div className="grid-2">
            <Card title="Status breakdown">
              <HBars title="Employees by status" bars={(Object.keys(STATUS_LABELS) as (keyof typeof s.counts)[])
                .filter((k) => s.counts[k]).map((k) => ({ label: STATUS_LABELS[k], value: s.counts[k], color: STATUS_COLORS[k] }))} />
            </Card>
            <Card title="Arrival times">
              <HBars title="Employees arriving in each 30-minute window" bars={data.arrivals.map((a) => ({ label: a.label, value: a.count, color: "#3a4a70" }))} />
            </Card>
            {bd.rows.length > 1 && (
              <Card title={`Attendance by ${bd.by.toLowerCase()}`}>
                <HBars title="Attendance % (tracked employees)" max={100} unit="%" bars={bd.rows
                  .filter((c) => c.attendance_pct !== null)
                  .map((c) => ({ label: c.name, value: c.attendance_pct as number, color: pctColor(c.attendance_pct as number) }))} />
              </Card>
            )}
          </div>

          {pk && pk.trend.length > 1 && (
            <div className="grid-2">
              <Card title={`Last ${pk.trend.length} report days · ${scopeLabel(scope)}`}>
                <Trend30 trend={pk.trend} title="Attendance % on working days, absent people per day" />
              </Card>
              <Card title="Attendance by weekday">
                <WeekdayHeat weekdays={pk.weekdays} extraHeader={pk.groups.length ? "30 days" : undefined}
                  note={`Last 12 weeks, working days only.${pk.groups.length ? " HOD teams lowest first – click one to open it." : ""}`}
                  rows={[{ name: "Everyone", heat: pk.heat_all, extra: "" },
                    ...pk.groups.map((g) => ({ name: g.name, heat: g.heat,
                      extra: <><span className="bar30"><i style={{ width: `${g.pct30 ?? 0}%`, background: pctColor30(g.pct30) }} /></span>{g.pct30 ?? "–"}%</>,
                      onClick: ins.hods?.some((h) => h.scope === `HOD:${g.name}`) ? () => setScope(`HOD:${g.name}`) : undefined }))]} />
              </Card>
            </div>
          )}

          {bd.rows.length > 1 && (
            <Card title={`By ${bd.by.toLowerCase()}`}>
              <DataTable exportName="breakdown" rows={bd.rows} rowKey={(x) => x.name} columns={[
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
              <DataTable search exportName="teams" rows={ins.hods} rowKey={(h) => h.scope} columns={[
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
            <DataTable search exportName="attendance" rows={rows.slice(0, 1000)} rowKey={(r) => r.code} columns={[
              { header: "Code", render: (r) => r.code },
              { header: "Name", render: (r) => <Link className="link" to={`/employee-report?code=${encodeURIComponent(r.code)}`}>{r.name}</Link> },
              ...(hasMaster ? [
                { header: "Department", render: (r: EmployeeRow) => r.department ?? "" },
                { header: "HOD", render: (r: EmployeeRow) => r.hod ?? "" },
                { header: "Team", render: (r: EmployeeRow) => r.team ?? "" },
                { header: "Manager", render: (r: EmployeeRow) => r.manager ?? "" },
              ] : [{ header: "Category", render: (r: EmployeeRow) => r.category }]),
              { header: "Status", render: (r) => <span className="st" style={{ background: `${STATUS_COLORS[r.status]}22`, color: STATUS_COLORS[r.status] }}>{r.status_label}</span> },
              ...(pk ? [{ header: "Last 30 days", value: (r: EmployeeRow) => p30(r)?.pct30 ?? -1, render: (r: EmployeeRow) => {
                const h = p30(r);
                return h ? <button type="button" className="link-btn" onClick={() => setPerson(r)} title="Open this person's last 30 report days">
                  <Strip30 strip={h.strip} pack={pk} legend={HO_LEGEND} mini /> <b style={{ color: pctColor30(h.pct30) }}>{h.pct30 === null ? "–" : `${h.pct30}%`}</b></button> : "";
              } }] : []),
              { header: "In", render: (r) => formatTime(r.in_time) },
              { header: "Out", render: (r) => formatTime(r.out_time) },
              { header: "Hours", render: (r) => formatHours(r.work_hours) },
              { header: "Late", render: (r) => (r.late_minutes ? `${formatMinutes(r.late_minutes)} hrs` : "") },
              { header: "Left early", render: (r) => (r.early_minutes ? `${formatMinutes(r.early_minutes)} hrs short` : "") },
              { header: "Leave", render: (r) => r.leave_type ?? "" },
              { header: "Permission", render: (r) => r.permission ?? "" },
              { header: "On duty", render: (r) => r.on_duty ?? "" },
            ]} />
          </Card>

          {person && pk && p30(person) && (() => {
            const h = p30(person) as HoPerson30;
            return (
              <Person30 title={person.name} subtitle={`EMP code ${person.code}${person.department ? ` · ${person.department}` : ""}${person.hod ? ` · HOD ${person.hod}` : ""}`}
                strip={h.strip} pack={pk} legend={HO_LEGEND} onClose={() => setPerson(null)}
                facts={[["Attendance", h.pct30 === null ? "–" : `${h.pct30}%`], ["Late days", h.late30], ["Absent days", h.absent30], ["Leave / half days", h.leave30],
                  ["WFH / on duty", h.wfh_od30], ["Usual in-time", h.usual_in], ["Average duty", h.avg_hours ? `${h.avg_hours} h` : ""],
                  [`${formatDate(date).slice(0, 6)}`, person.status_label]]}>
                <p style={{ marginTop: ".8rem" }}><Link className="btn btn-ghost btn-small" to={`/employee-report?code=${encodeURIComponent(person.code)}`}>Full employee report</Link></p>
              </Person30>
            );
          })()}

          {day.data && day.data.emails.length > 0 && (
            <Card title="Emails for this day">
              <DataTable rows={day.data.emails} rowKey={(e) => `${e.scope}-${e.sent_at}`} columns={[
                { header: "To", render: (e) => scopeLabel(e.scope) },
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
