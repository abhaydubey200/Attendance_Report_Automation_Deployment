// Module 2 screens that match Module 1's: attendance report (any dates), one employee, email log, automation and month-end.
import { useEffect, useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, apiUrl } from "../api/client";
import { useAction, useApi } from "../api/useApi";
import { useAuth } from "../auth/AuthContext";
import { useConfirm } from "../components/feedback";
import { ActionMessages, Card, DataTable, ErrorNotice, Field, KpiCard, Loading, Notice, PageHeader, Toolbar } from "../components/ui";
import { formatDate, formatDateTime } from "../format";
import type { SalesEmailLogRow, SalesEmployeeReport, SalesHolidays, SalesJobs, SalesMailItem, SalesMonthList, SalesMonthMail, SalesReport, SalesStaffRow } from "./types";
import { STATUS_COLOR } from "./types";

const pctText = (v: number | null | undefined) => (v === null || v === undefined ? "–" : `${v}%`);
const tone = (v: number | null | undefined) => (v === null || v === undefined ? "info" : v >= 90 ? "ok" : v >= 75 ? "warn" : "fail") as "ok" | "warn" | "fail" | "info";
const statusKind = (s: string) => (s === "FAILED" ? "fail" : s === "HELD" || s === "PARTIAL" ? "warn" : ["SENT", "SAVED", "TEST_SENT", "SUCCESS"].includes(s) ? "ok" : "info");
const days = (n: number) => `${n} day${n === 1 ? "" : "s"}`;
const qs = (o: Record<string, string>) => new URLSearchParams(Object.entries(o).filter(([, v]) => v)).toString();

function DateRange({ start, end, onChange }: { start: string; end: string; onChange: (s: string, e: string) => void }) {
  return (
    <>
      <label className="field inline"><span className="field-label">From</span><input type="date" value={start} onChange={(e) => onChange(e.target.value, end)} /></label>
      <label className="field inline"><span className="field-label">To</span><input type="date" value={end} onChange={(e) => onChange(start, e.target.value)} /></label>
    </>
  );
}

// ---------------------------------------------------------------- Attendance report
export function SalesReportPage() {
  const [p, setP] = useSearchParams();
  const f = { start: p.get("start") ?? "", end: p.get("end") ?? "", hod: p.get("hod") ?? "", team: p.get("team") ?? "" };
  const set = (o: Partial<typeof f>) => setP(qs({ ...f, ...o }));
  const query = qs(f);
  const rep = useApi<SalesReport>(`/v1/sales/reports/attendance${query ? `?${query}` : ""}`);
  const [only, setOnly] = useState<"all" | "repeat" | "absent">("all");
  const r = rep.data;
  const people = (r?.people ?? []).filter((x) => only === "all" || (only === "repeat" ? x.repeat.length > 0 : x.absent > 0));
  return (
    <>
      <PageHeader title="Attendance report" subtitle="Any date range (up to six months). Warning signs that repeat are the patterns worth a conversation."
        actions={<Toolbar>
          <DateRange start={f.start || r?.from || ""} end={f.end || r?.to || ""} onChange={(s, e) => set({ start: s, end: e })} />
          <a className="btn btn-ghost btn-small" href={apiUrl(`/v1/sales/reports/attendance/excel${query ? `?${query}` : ""}`)}>Excel</a>
        </Toolbar>} />
      {rep.error && <ErrorNotice error={rep.error} />}
      {rep.loading || !r ? <Loading /> : (
        <>
          <div className="kpi-grid">
            <KpiCard label="Attendance" value={pctText(r.totals.attendance_pct)} tone={tone(r.totals.attendance_pct)} hint={`${formatDate(r.from)} – ${formatDate(r.to)} · ${days(r.days_uploaded)}`} />
            <KpiCard label="Absent days" value={r.totals.absent} tone="fail" />
            <KpiCard label="Late days" value={r.totals.late} tone="warn" />
            <KpiCard label="Days needing checking" value={r.totals.flagged_days} tone="brand" />
            <KpiCard label="Repeated warning signs" value={r.totals.repeat_people} tone={r.totals.repeat_people ? "fail" : "ok"} hint={`same sign on ${r.repeat_days}+ days`} />
          </div>
          <Card title="By day">
            <div className="sales-trend" role="img" aria-label="Attendance by day">
              {r.days.map((d) => (
                <span key={d.date} title={`${formatDate(d.date)}: ${pctText(d.attendance_pct)} · ${d.absent} absent · ${d.flagged} to check`}>
                  <i style={{ height: `${Math.max(4, d.attendance_pct ?? 0)}%`, background: (d.attendance_pct ?? 0) >= 90 ? "#16a34a" : (d.attendance_pct ?? 0) >= 75 ? "#d97706" : "#dc2626" }} />
                  <small>{d.date.slice(8)}</small>
                </span>
              ))}
            </div>
          </Card>
          <Card title="People">
            <Toolbar>
              {[["all", "Everyone"], ["repeat", "Repeated warning signs"], ["absent", "Had absent days"]].map(([k, l]) => (
                <button type="button" key={k} className={`chip-btn${only === k ? " on" : ""}`} onClick={() => setOnly(k as typeof only)}>{l}</button>))}
              <label className="field inline"><span className="field-label">HOD</span>
                <select value={f.hod} onChange={(e) => set({ hod: e.target.value })}><option value="">All</option>{r.filters.hods.map((h) => <option key={h}>{h}</option>)}</select></label>
              <label className="field inline"><span className="field-label">Team head</span>
                <select value={f.team} onChange={(e) => set({ team: e.target.value })}><option value="">All</option>{r.filters.teams.map((h) => <option key={h}>{h}</option>)}</select></label>
            </Toolbar>
            <DataTable rows={people} rowKey={(x) => x.code} search exportName={`field_sales_${r.from}_${r.to}`} columns={[
              { header: "Employee", render: (x) => <Link to={`/sales/employee?${qs({ code: x.code, start: r.from, end: r.to })}`}><strong>{x.name}</strong> <span className="muted">{x.code}</span></Link>, value: (x) => `${x.name} ${x.code}` },
              { header: "Role", render: (x) => x.designation },
              { header: "Team head", render: (x) => x.team_head },
              { header: "Days", render: (x) => x.days },
              { header: "Attendance", render: (x) => <strong style={{ color: tone(x.attendance_pct) === "ok" ? "#15803d" : tone(x.attendance_pct) === "warn" ? "#b45309" : "#b91c1c" }}>{pctText(x.attendance_pct)}</strong>, value: (x) => x.attendance_pct },
              { header: "Absent", render: (x) => x.absent || "" , value: (x) => x.absent },
              { header: "Late", render: (x) => x.late || "", value: (x) => x.late },
              { header: "Leave", render: (x) => x.leave || "", value: (x) => x.leave },
              { header: "Avg in market", render: (x) => x.avg_market },
              { header: "To check", render: (x) => x.flag_days || "", value: (x) => x.flag_days },
              { header: "Repeated", render: (x) => <span className="sales-flags">{x.repeat.map((w) => <span key={w} className="badge badge-fail">{w}</span>)}</span>, value: (x) => x.repeat.join("; ") },
            ]} />
          </Card>
        </>
      )}
    </>
  );
}

// ---------------------------------------------------------------- One employee
export function SalesEmployeePage() {
  const [p, setP] = useSearchParams();
  const code = p.get("code") ?? "";
  const [typed, setTyped] = useState(code);
  const start = p.get("start") ?? "", end = p.get("end") ?? "";
  const q = qs({ start, end });
  const rep = useApi<SalesEmployeeReport>(code ? `/v1/sales/reports/employee/${encodeURIComponent(code)}${q ? `?${q}` : ""}` : null);
  const e = rep.data;
  return (
    <>
      <PageHeader title="Employee report" subtitle="One person day by day: status, times, time in market and warning signs."
        actions={<Toolbar>
          <form className="toolbar" onSubmit={(ev) => { ev.preventDefault(); setP(qs({ code: typed.trim().toUpperCase(), start, end })); }}>
            <label className="field inline"><span className="field-label">Code</span><input value={typed} placeholder="SL01234" onChange={(ev) => setTyped(ev.target.value)} /></label>
            <button type="submit" className="btn btn-primary btn-small">Show</button>
          </form>
          {code && <DateRange start={start || e?.from || ""} end={end || e?.to || ""} onChange={(s, en) => setP(qs({ code, start: s, end: en }))} />}
        </Toolbar>} />
      {!code && <Notice>Enter an employee code, or open a person from the <Link to="/sales/report">attendance report</Link>.</Notice>}
      {rep.error && <ErrorNotice error={rep.error} />}
      {code && (rep.loading || !e) ? (rep.error ? null : <Loading />) : e && (
        <>
          <Card>
            <p><strong style={{ fontSize: 18 }}>{e.name}</strong> <span className="muted">{e.code} · {e.designation}</span> <span className={`badge badge-${e.status === "ACTIVE" ? "ok" : "warn"}`}>{e.status}</span></p>
            <p className="muted">Team head: {e.team_head || "—"}{e.team_head_email && ` (${e.team_head_email})`} · HOD: {e.hod || "—"}</p>
          </Card>
          <div className="kpi-grid">
            <KpiCard label="Attendance" value={pctText(e.summary.attendance_pct)} tone={tone(e.summary.attendance_pct)} hint={days(e.summary.days)} />
            <KpiCard label="Absent" value={e.summary.absent} tone="fail" />
            <KpiCard label="Late" value={e.summary.late} tone="warn" />
            <KpiCard label="Leave · week off" value={`${e.summary.leave} · ${e.summary.week_off}`} />
            <KpiCard label="Days needing checking" value={e.summary.flagged_days} tone="brand" />
          </div>
          <Card title="Day by day">
            <DataTable rows={e.days} rowKey={(d) => d.date} exportName={`field_sales_${e.code}`} columns={[
              { header: "Date", render: (d) => <Link to={`/sales/day?date=${d.date}`}>{formatDate(d.date)}</Link>, value: (d) => d.date },
              { header: "Status", render: (d) => <><strong style={{ color: STATUS_COLOR[d.status] }}>{d.status_label}</strong>{d.leave && <div className="muted small">{d.leave}</div>}{d.not_marked && <div className="muted small">did not mark</div>}</>, value: (d) => d.status_label },
              { header: "Marked", render: (d) => d.att },
              { header: "Activity", render: (d) => (d.first ? `${d.first} – ${d.last}` : "") },
              { header: "In market", render: (d) => d.market },
              { header: "KM", render: (d) => d.km ?? "" },
              { header: "Day end", render: (d) => d.eod },
              { header: "Visits", render: (d) => (d.calls === null ? "" : `${d.calls}${d.productive !== null ? ` (${d.productive} orders)` : ""}`) },
              { header: "Warning signs", render: (d) => <span className="sales-flags">{d.warnings.map((w) => <span key={w} className="badge badge-warn">{w}</span>)}</span>, value: (d) => d.warnings.join("; ") },
            ]} />
          </Card>
        </>
      )}
    </>
  );
}

// ---------------------------------------------------------------- Email log
export function SalesEmailLogPage() {
  const log = useApi<SalesEmailLogRow[]>("/v1/sales/emails");
  return (
    <>
      <PageHeader title="Email log" subtitle="Every Field Sales email sent or saved (test mode), daily and month-end." />
      {log.error && <ErrorNotice error={log.error} />}
      {log.loading ? <Loading /> : (
        <Card>
          <DataTable rows={log.data ?? []} rowKey={(r) => String(r.id)} search exportName="field_sales_email_log" empty="No emails sent yet." columns={[
            { header: "Sent", render: (r) => formatDateTime(r.sent_at), value: (r) => r.sent_at },
            { header: "Kind", render: (r) => r.kind },
            { header: "For", render: (r) => formatDate(r.report_date), value: (r) => r.report_date },
            { header: "Recipient", render: (r) => <><strong>{r.recipient}</strong><div className="muted small">{r.role}</div></>, value: (r) => r.recipient },
            { header: "To", render: (r) => <span className="wrap-any">{r.to || "—"}</span> },
            { header: "Status", render: (r) => <><span className={`badge badge-${statusKind(r.status)}`}>{r.status.replace("_", " ")}</span>{r.note && <div className="muted small">{r.note}</div>}</>, value: (r) => r.status },
            { header: "By", render: (r) => r.sent_by ?? "" },
            { header: "", sortable: false, render: (r) => <a className="btn btn-ghost btn-small" href={apiUrl(`/v1/sales/mail/${r.id}/preview`)} target="_blank" rel="noreferrer">View</a> },
          ]} />
        </Card>
      )}
    </>
  );
}

// ---------------------------------------------------------------- Automation + month-end
function MailList({ items, preview, setPreview }: { items: SalesMailItem[]; preview: number | null; setPreview: (id: number | null) => void }) {
  return (
    <DataTable rows={items} rowKey={(i) => String(i.id)} columns={[
      { header: "Recipient", render: (i) => <><strong>{i.name}</strong><div className="muted small">{i.role}</div></>, value: (i) => i.name },
      { header: "To", render: (i) => <span className="wrap-any">{i.to || "—"}</span> },
      { header: "People", render: (i) => i.counts.people ?? "" },
      { header: "Attendance", render: (i) => pctText(i.counts.attendance_pct) },
      { header: "Need a talk", render: (i) => i.counts.flagged ?? "" },
      { header: "Status", render: (i) => <><span className={`badge badge-${statusKind(i.status)}`}>{i.status.replace("_", " ")}</span>{i.note && <div className="muted small">{i.note}</div>}</>, value: (i) => i.status },
      { header: "", sortable: false, render: (i) => <button type="button" className="btn btn-ghost btn-small" onClick={() => setPreview(preview === i.id ? null : i.id)}>Preview</button> },
    ]} />
  );
}

export function SalesAutomationPage() {
  const jobs = useApi<SalesJobs>("/v1/sales/jobs");
  const months = useApi<SalesMonthList>("/v1/sales/monthly");
  const [month, setMonth] = useState("");
  const [day, setDay] = useState("");
  const [preview, setPreview] = useState<number | null>(null);
  useEffect(() => { if (months.data && !month) setMonth(months.data.months.find((m) => m.month === months.data!.default)?.month ?? months.data.months[0]?.month ?? months.data.default); }, [months.data, month]);
  const mm = useApi<SalesMonthMail>(month ? `/v1/sales/monthly/${month}` : null);
  const { busy, error, message, run } = useAction();
  const ask = useConfirm();
  const { hasPermission } = useAuth();
  const canRun = hasPermission("UPLOAD_AND_SEND");
  const sendable = mm.data?.items.filter((i) => i.sendable) ?? [];

  async function runDaily(e: FormEvent) {
    e.preventDefault();
    await run(() => api.post<{ status: string; problem?: string; people?: number }>("/v1/sales/jobs/daily", { day: day || null }),
      (r) => (r.status === "FAILED" ? `Not done: ${r.problem ?? "see the job history"}` : `Done: ${r.people ?? 0} people counted. Emails are on Approve emails.`));
    jobs.reload();
  }
  async function generate() {
    if (mm.data?.items.length && !(await ask({ title: "Prepare again?", message: "Unsent month-end emails are replaced. Sent ones are never sent twice.", confirmLabel: "Prepare again" }))) return;
    await run(() => api.post("/v1/sales/monthly/generate", { month }), "Month-end emails prepared.");
    mm.reload(); months.reload(); jobs.reload();
  }
  async function approve() {
    const live = mm.data?.mode === "live";
    if (!(await ask({ title: live ? "Send the month-end emails?" : "Approve the month-end emails?", confirmLabel: live ? "Send" : "Approve", danger: live,
      message: live ? `${sendable.length} month-end emails will be sent.` : `Test mode: ${sendable.length} emails are saved to the outbox, nothing is sent.` }))) return;
    await run(() => api.post(`/v1/sales/monthly/${month}/approve`, {}), live ? "Sent." : "Saved to the outbox (test mode).");
    mm.reload();
  }
  const j = jobs.data;
  return (
    <>
      <PageHeader title="Automation" subtitle="The daily job reads the Bizom files dropped in the Field Sales inbox folder; month-end emails are prepared on the 1st." />
      <ActionMessages error={error} message={message} />
      {jobs.error && <ErrorNotice error={jobs.error} />}
      <div className="grid-2">
        <Card title="Daily job">
          {!j ? <Loading /> : (
            <>
              <p className="muted small">Inbox folder (Bizom Attendance, EOD and Call Variance files of the day):</p>
              <p><code className="wrap-any">{j.inbox}</code></p>
              <p>{j.waiting.length ? <>Waiting: {j.waiting.join(" · ")}</> : <span className="muted">The inbox is empty.</span>}</p>
              <p className="muted small">Scheduled task <b>APIS Field Sales Daily</b> runs <code>main.py sales-run-daily</code> each morning for yesterday. Processed files are deleted (they hold phone numbers and GPS).
                Emails then {j.auto_send ? <b>go out automatically</b> : <>wait on <Link to="/sales/mail">Approve emails</Link></>} ({j.mode === "test" ? "test mode: saved, not sent" : "live"}).</p>
              {canRun && (
                <form className="toolbar" onSubmit={runDaily}>
                  <label className="field inline"><span className="field-label">Day</span><input type="date" value={day} onChange={(e) => setDay(e.target.value)} /></label>
                  <button type="submit" className="btn btn-primary btn-small" disabled={busy}>{busy ? "Running…" : "Run now"}</button>
                  <span className="muted small">empty = yesterday</span>
                </form>
              )}
            </>
          )}
        </Card>
        <Card title="Month-end" actions={<Toolbar>
          <select value={month} onChange={(e) => { setMonth(e.target.value); setPreview(null); }} aria-label="Month">
            {(months.data?.months ?? []).map((m) => <option key={m.month} value={m.month}>{m.label} ({m.days} days)</option>)}
          </select>
          {canRun && <button type="button" className="btn btn-ghost btn-small" disabled={busy || !month} onClick={() => void generate()}>Prepare</button>}
          {canRun && <button type="button" className="btn btn-primary btn-small" disabled={busy || !sendable.length} onClick={() => void approve()}>{mm.data?.mode === "live" ? "Approve & send" : "Approve (test)"} ({sendable.length})</button>}
        </Toolbar>}>
          <p className="muted small">One short email per team head, zonal head, HOD, Director and HR with an Excel workbook and a dashboard: attendance, week by week, people who need a conversation (3+ absent days, 5+ late days or the same warning sign on 3+ days) and full attendance.</p>
          {mm.loading ? <Loading /> : !mm.data?.items.length ? <p className="muted">Not prepared yet for this month.</p> : <MailList items={mm.data.items} preview={preview} setPreview={setPreview} />}
        </Card>
      </div>
      {preview && (
        <Card title="Preview" actions={<Toolbar>
          <a className="btn btn-ghost btn-small" href={apiUrl(`/v1/sales/mail/${preview}/attachment/excel`)}>Excel</a>
          <a className="btn btn-ghost btn-small" href={apiUrl(`/v1/sales/mail/${preview}/attachment/dashboard`)}>Dashboard</a>
          <button type="button" className="btn btn-ghost btn-small" onClick={() => setPreview(null)}>Close</button></Toolbar>}>
          <iframe className="email-frame" sandbox="" title="Email preview" src={apiUrl(`/v1/sales/mail/${preview}/preview`)} />
        </Card>
      )}
      <HolidaysCard />
      <Card title="Job history">
        <DataTable rows={j?.runs ?? []} rowKey={(r) => String(r.id)} empty="No runs yet." columns={[
          { header: "Started", render: (r) => formatDateTime(r.started_at), value: (r) => r.started_at },
          { header: "Job", render: (r) => `${r.job === "DAILY" ? "Daily" : "Month-end"} ${r.target ?? ""}` },
          { header: "How", render: (r) => `${r.trigger.toLowerCase()} · ${r.started_by}` },
          { header: "Result", render: (r) => <span className={`badge badge-${statusKind(r.status)}`}>{r.status}</span>, value: (r) => r.status },
          { header: "Details", render: (r) => <span className="small">{r.error ?? summaryText(r.summary)}</span> },
          { header: "Took", render: (r) => (r.seconds === null ? "" : `${r.seconds}s`) },
        ]} />
      </Card>
    </>
  );
}

// ---------------------------------------------------------------- Holiday calendar (HR confirms; the app never decides)
export function HolidaysCard() {
  const h = useApi<SalesHolidays>("/v1/sales/holidays");
  const { busy, error, message, run } = useAction();
  const { hasPermission } = useAuth();
  const can = hasPermission("MANAGE_SETTINGS");
  const [day, setDay] = useState("");
  const [name, setName] = useState("");
  async function decide(d: string, kind: "holiday" | "working" | "clear", n = "") {
    await run(() => api.put(`/v1/sales/holidays/${d}`, { kind, name: n }),
      kind === "holiday" ? `${formatDate(d)} saved as a holiday.` : kind === "working" ? `${formatDate(d)} saved as a working day.` : `${formatDate(d)} cleared.`);
    h.reload();
  }
  const d = h.data;
  return (
    <Card title="Holidays (field sales)">
      <ActionMessages error={error} message={message} />
      {!d ? <Loading /> : (
        <>
          <p className="muted small">{d.rule} On a holiday, people who did not mark attendance count as off, not absent.</p>
          {d.waiting.length > 0 && (
            <Notice kind="warn">
              <b>Waiting for HR – the emails of these days are held:</b>
              <ul className="plain">{d.waiting.map((w) => (
                <li key={w.date}>{formatDate(w.date)} ({w.weekday}) – only {w.marked} of {w.expected} marked attendance{" "}
                  {can && <><button type="button" className="btn btn-primary btn-small" disabled={busy} onClick={() => void decide(w.date, "holiday", "")}>Holiday</button>{" "}
                    <button type="button" className="btn btn-ghost btn-small" disabled={busy} onClick={() => void decide(w.date, "working")}>Working day</button></>}
                </li>))}</ul>
            </Notice>
          )}
          <DataTable rows={[...d.holidays.map((x) => ({ ...x, kind: "Holiday" })), ...d.working_days.map((x) => ({ date: x, name: "", kind: "Working day" }))]
            .sort((a, b) => a.date.localeCompare(b.date))} rowKey={(r) => r.date} empty="No days confirmed yet." columns={[
            { header: "Date", render: (r) => formatDate(r.date), value: (r) => r.date },
            { header: "Confirmed as", render: (r) => r.kind },
            { header: "Name", render: (r) => r.name },
            { header: "", render: (r) => (can ? <button type="button" className="btn btn-ghost btn-small" disabled={busy} onClick={() => void decide(r.date, "clear")}>Remove</button> : null) },
          ]} />
          {can && (
            <form className="toolbar" onSubmit={(e) => { e.preventDefault(); if (day) void decide(day, "holiday", name).then(() => { setDay(""); setName(""); }); }}>
              <label className="field inline"><span className="field-label">Add a holiday</span><input type="date" value={day} onChange={(e) => setDay(e.target.value)} /></label>
              <label className="field inline"><span className="field-label">Name</span><input value={name} maxLength={60} onChange={(e) => setName(e.target.value)} placeholder="e.g. Diwali" /></label>
              <button type="submit" className="btn btn-primary btn-small" disabled={busy || !day}>Save</button>
            </form>
          )}
        </>
      )}
    </Card>
  );
}

function summaryText(s: Record<string, unknown> | null): string {
  if (!s) return "";
  const parts: string[] = [];
  if (typeof s.people === "number") parts.push(`${s.people} people`);
  if (Array.isArray(s.processed) && s.processed.length) parts.push(`files: ${s.processed.join(", ")}`);
  if (s.emails && typeof s.emails === "object") parts.push(`emails: ${Object.entries(s.emails as Record<string, number>).map(([k, v]) => `${v} ${k.toLowerCase()}`).join(", ")}`);
  if (typeof s.note === "string") parts.push(s.note);
  if (Array.isArray(s.rejected_files) && s.rejected_files.length) parts.push(`skipped: ${s.rejected_files.length} file(s)`);
  return parts.join(" · ");
}

// ---------------------------------------------------------------- Staff add / edit form
const STAFF_FIELDS: [keyof SalesStaffRow, string][] = [
  ["name", "Name"], ["designation", "Role (SO, SR, ASE…)"], ["zone", "Zone"], ["hq", "HQ"],
  ["manager_name", "Team head"], ["manager_email", "Team head email"], ["zonal_name", "Zonal head"], ["zonal_email", "Zonal head email"],
  ["hod_name", "HOD"], ["hod_email", "HOD email"], ["date_of_joining", "Date of joining (YYYY-MM-DD)"],
];

export function StaffEditor({ row, onDone }: { row: SalesStaffRow | "new"; onDone: () => void }) {
  const isNew = row === "new";
  const [v, setV] = useState<Record<string, string>>(() => {
    const o: Record<string, string> = { code: isNew ? "" : row.code };
    STAFF_FIELDS.forEach(([k]) => { o[k] = isNew ? "" : String(row[k] ?? ""); });
    return o;
  });
  const { busy, error, run } = useAction();
  async function save(e: FormEvent) {
    e.preventDefault();
    const body = Object.fromEntries(Object.entries(v).map(([k, x]) => [k, x.trim() || null]));
    const ok = await run(() => (isNew ? api.post("/v1/sales/staff", body) : api.put(`/v1/sales/staff/${row.code}`, body)), "Saved.");
    if (ok) onDone();
  }
  return (
    <Card title={isNew ? "Add a person" : `Edit ${row.name} (${row.code})`}>
      <form onSubmit={save}>
        <div className="form-grid">
          {isNew && <Field label="Employee code"><input value={v.code} required placeholder="SL04650" onChange={(e) => setV({ ...v, code: e.target.value })} /></Field>}
          {STAFF_FIELDS.map(([k, l]) => (
            <Field key={k} label={l}><input value={v[k]} required={k === "name"} onChange={(e) => setV({ ...v, [k]: e.target.value })} /></Field>
          ))}
        </div>
        <ActionMessages error={error} message={null} />
        <Toolbar>
          <button type="submit" className="btn btn-primary btn-small" disabled={busy}>{busy ? "Saving…" : "Save"}</button>
          <button type="button" className="btn btn-ghost btn-small" onClick={onDone}>Cancel</button>
        </Toolbar>
      </form>
    </Card>
  );
}
