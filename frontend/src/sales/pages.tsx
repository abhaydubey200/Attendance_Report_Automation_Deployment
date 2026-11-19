import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api, apiUrl } from "../api/client";
import { useAction, useApi } from "../api/useApi";
import { useAuth } from "../auth/AuthContext";
import { useConfirm } from "../components/feedback";
import { Icon } from "../components/icons";
import { ActionMessages, Card, DataTable, ErrorNotice, Field, KpiCard, Loading, Notice, PageHeader, Toolbar } from "../components/ui";
import { formatDate, formatDateTime } from "../format";
import type { SalesDay, SalesDayMail, SalesDayRow, SalesEmailSettings, SalesPerson, SalesRules, SalesStaff, SalesStatus } from "./types";
import { STATUS_COLOR } from "./types";

const pctText = (v: number | null | undefined) => (v === null || v === undefined ? "–" : `${v}%`);
const tone = (v: number | null | undefined) => (v === null || v === undefined ? "info" : v >= 90 ? "ok" : v >= 75 ? "warn" : "fail") as "ok" | "warn" | "fail" | "info";
const LEVEL_KIND = { high: "fail", medium: "warn", low: "info" } as const;

function StatusText({ s, label }: { s: SalesStatus; label: string }) {
  return <strong style={{ color: STATUS_COLOR[s] }}>{label}</strong>;
}

function Flags({ p }: { p: SalesPerson }) {
  return (
    <span className="sales-flags">
      {p.flags.map((f) => <span key={f.code} className={`badge badge-${LEVEL_KIND[f.level]}`} title={f.why}>{f.label}</span>)}
    </span>
  );
}

// ---------------------------------------------------------------- Overview
export function SalesOverview() {
  const days = useApi<SalesDayRow[]>("/v1/sales/days");
  const staff = useApi<SalesStaff>("/v1/sales/staff");
  const latest = days.data?.[0];
  return (
    <>
      <PageHeader title="Field Sales attendance" subtitle="Daily attendance of the field sales teams from Bizom, with the warning signs managers should check."
        actions={<Link className="btn btn-primary btn-auto" to="/sales/upload"><Icon name="upload" className="btn-icon" /> Upload a day</Link>} />
      {days.error && <ErrorNotice error={days.error} />}
      {staff.data && staff.data.summary.total === 0 && (
        <Notice kind="warn">The field sales staff list is empty. <Link to="/sales/staff">Import HR's staff list</Link> first: it decides who is
          expected to mark attendance and who receives the emails.</Notice>
      )}
      {days.loading ? <Loading /> : !latest ? (
        <Card title="No day uploaded yet">
          <p>Upload yesterday's Bizom <b>Attendance report</b> (CSV). The <b>Attendance &amp; EOD</b> and <b>Call Variance</b> reports are optional
            and add the day-end and outlet-visit checks.</p>
          <Link className="btn btn-primary btn-auto" to="/sales/upload">Upload a day</Link>
        </Card>
      ) : (
        <>
          <div className="kpi-grid">
            <KpiCard label={`Attendance on ${formatDate(latest.report_date)}`} value={pctText(latest.attendance_pct)} tone={tone(latest.attendance_pct)} hint={`${latest.people} people`} />
            <KpiCard label="Absent (did not mark)" value={latest.absent} tone="fail" />
            <KpiCard label="Late" value={latest.late} tone="warn" />
            <KpiCard label="Needs checking" value={latest.flagged} tone="brand" hint={<Link to={`/sales/day?date=${latest.report_date}`}>See who and why</Link>} />
          </div>
          <Card title="Uploaded days">
            <DataTable rows={days.data ?? []} rowKey={(d) => d.report_date} exportName="field_sales_days" columns={[
              { header: "Date", render: (d) => <Link to={`/sales/day?date=${d.report_date}`}>{formatDate(d.report_date)}</Link>, value: (d) => d.report_date },
              { header: "People", render: (d) => d.people },
              { header: "Attendance", render: (d) => pctText(d.attendance_pct), value: (d) => d.attendance_pct },
              { header: "Absent", render: (d) => d.absent },
              { header: "Late", render: (d) => d.late },
              { header: "Needs checking", render: (d) => d.flagged },
              { header: "Reports", render: (d) => ["Attendance", d.files?.eod && "EOD", d.files?.calls && "Calls"].filter(Boolean).join(" + ") },
              { header: "Uploaded", render: (d) => `${formatDateTime(d.uploaded_at)} · ${d.uploaded_by}`, value: (d) => d.uploaded_at },
            ]} />
          </Card>
        </>
      )}
    </>
  );
}

// ---------------------------------------------------------------- Upload
export function SalesUpload() {
  const [files, setFiles] = useState<File[]>([]);
  const [replace, setReplace] = useState(false);
  const { busy, error, message, run } = useAction();
  const navigate = useNavigate();
  async function submit(e: FormEvent) {
    e.preventDefault();
    const form = new FormData();
    files.forEach((f) => form.append("files", f));
    form.append("replace", String(replace));
    const day = await run(() => api.upload<SalesDay>("/v1/sales/upload", form),
      (d) => `${formatDate(d.report_date)} processed: ${d.people} people, ${d.summary.people_flagged} need checking.`);
    if (day) navigate(`/sales/day?date=${day.report_date}`);
  }
  return (
    <>
      <PageHeader title="Upload a Bizom day" subtitle="Choose one to three Bizom reports of the same day. Each file is recognised by its columns." />
      <Card>
        <form onSubmit={submit} className="sales-upload">
          <ol className="sales-steps">
            <li><strong>Attendance report</strong> <span className="badge badge-fail">required</span><span>Status, attendance time, time in market, KM.</span></li>
            <li><strong>Attendance &amp; EOD report</strong> <span className="badge badge-info">optional</span><span>Adds the day-end checks (day not closed, short day).</span></li>
            <li><strong>Call Variance report</strong> <span className="badge badge-info">optional</span><span>Adds the outlet-visit checks (short visits, away from the outlet, impossible travel).</span></li>
          </ol>
          <Field label="Bizom files (.csv)">
            <input type="file" multiple accept=".csv,.xlsx" onChange={(e) => setFiles([...(e.target.files ?? [])].slice(0, 3))} />
          </Field>
          {files.length > 0 && <p className="muted">{files.map((f) => f.name).join(" · ")}</p>}
          <label className="check"><input type="checkbox" checked={replace} onChange={(e) => setReplace(e.target.checked)} /> Replace the day if it is already uploaded</label>
          <p className="muted">Phone numbers, attendance photos and GPS positions in the files are never stored.</p>
          <ActionMessages error={error} message={message} />
          <button type="submit" className="btn btn-primary btn-auto" disabled={busy || files.length === 0}>{busy ? "Processing…" : "Process the day"}</button>
        </form>
      </Card>
    </>
  );
}

// ---------------------------------------------------------------- Day insights
function useDayParam(days: SalesDayRow[] | null) {
  const [params, setParams] = useSearchParams();
  const date = params.get("date") ?? days?.[0]?.report_date ?? null;
  return [date, (d: string) => setParams({ date: d })] as const;
}

function DayPicker({ days, date, onChange }: { days: SalesDayRow[]; date: string | null; onChange: (d: string) => void }) {
  return (
    <label className="field inline"><span className="field-label">Day</span>
      <select value={date ?? ""} onChange={(e) => onChange(e.target.value)}>
        {days.map((d) => <option key={d.report_date} value={d.report_date}>{formatDate(d.report_date)}</option>)}
      </select>
    </label>
  );
}

export function SalesDayPage() {
  const days = useApi<SalesDayRow[]>("/v1/sales/days");
  const [date, setDate] = useDayParam(days.data);
  const day = useApi<SalesDay>(date ? `/v1/sales/days/${date}` : null);
  const [filter, setFilter] = useState<string>("flagged");
  const [open, setOpen] = useState<string | null>(null);
  const rows = useMemo(() => {
    const all = day.data?.rows ?? [];
    if (filter === "all") return all;
    if (filter === "flagged") return all.filter((p) => p.flags.length);
    if (filter.startsWith("w:")) return all.filter((p) => p.flags.some((f) => f.code === filter.slice(2)));
    return all.filter((p) => p.status === filter);
  }, [day.data, filter]);
  if (days.loading) return <Loading />;
  if (!days.data?.length) return <><PageHeader title="Day insights" /><Notice>No Bizom day uploaded yet. <Link to="/sales/upload">Upload a day</Link>.</Notice></>;
  const s = day.data?.summary;
  return (
    <>
      <PageHeader title="Day insights" subtitle={s ? `${formatDate(s.date)} · ${s.people} people` : undefined}
        actions={<Toolbar>
          <DayPicker days={days.data} date={date} onChange={setDate} />
          {date && <a className="btn btn-ghost btn-small" href={apiUrl(`/v1/sales/days/${date}/excel`)}>Excel</a>}
          {date && <a className="btn btn-ghost btn-small" href={apiUrl(`/v1/sales/days/${date}/dashboard`)}>Dashboard</a>}
        </Toolbar>} />
      {day.error && <ErrorNotice error={day.error} />}
      {day.loading || !s || !day.data ? <Loading /> : (
        <>
          <div className="kpi-grid">
            <KpiCard label="Attendance" value={pctText(s.attendance_pct)} tone={tone(s.attendance_pct)} hint={`${s.counts.PRESENT} present · ${s.counts.HALF_DAY} half day`} />
            <KpiCard label="Absent" value={s.counts.ABSENT} tone="fail" hint={`${s.not_marked} did not mark`} />
            <KpiCard label="Late" value={s.counts.LATE} tone="warn" hint="after 10:30 AM" />
            <KpiCard label="Leave · week off" value={`${s.counts.LEAVE} · ${s.counts.WEEK_OFF}`} />
            <KpiCard label="Needs checking" value={s.people_flagged} tone="brand" hint={`${s.people_high} serious`} />
          </div>
          {(s.data.not_in_staff_list.length > 0 || !s.files.eod || !s.files.calls) && (
            <Notice kind="warn">
              {s.data.not_in_staff_list.length > 0 && <>{s.data.not_in_staff_list.length} people marked attendance but are not on the staff list (in the HR email). </>}
              {!s.files.eod && <>No EOD report: day-end checks skipped. </>}
              {!s.files.calls && <>No Call Variance report: outlet-visit checks skipped.</>}
            </Notice>
          )}
          <div className="grid-2">
            <Card title="Warning signs — for checking, not proof">
              {day.data.warnings.length === 0 ? <p className="muted">Nothing to check on this day.</p> : (
                <ul className="sales-warn">
                  {day.data.warnings.map((w) => (
                    <li key={w.code}><button type="button" className={filter === `w:${w.code}` ? "on" : ""} onClick={() => setFilter(`w:${w.code}`)} title={w.why}>
                      <i className={`lv-${w.level}`} /> <span>{w.label}</span> <b>{w.n}</b></button></li>
                  ))}
                </ul>
              )}
              <p className="muted small">Supervisors (ASE / ASM / TSM / RSM…) are not checked for market activity.</p>
            </Card>
            <Card title="Teams — lowest attendance first">
              <DataTable rows={day.data.teams} rowKey={(t) => `${t.hod}|${t.zonal}`} pageSize={8} columns={[
                { header: "Zonal head", render: (t) => t.zonal }, { header: "HOD", render: (t) => t.hod },
                { header: "People", render: (t) => t.people }, { header: "Attendance", render: (t) => pctText(t.pct), value: (t) => t.pct },
                { header: "Absent", render: (t) => t.absent }, { header: "To check", render: (t) => t.flagged },
              ]} />
            </Card>
          </div>
          <Card title="People">
            <div className="chips-row">
              {[["flagged", "Needs checking"], ["all", "Everyone"], ["ABSENT", "Absent"], ["LATE", "Late"], ["HALF_DAY", "Half day"], ["LEAVE", "Leave"], ["WEEK_OFF", "Week off"], ["PRESENT", "Present"]]
                .map(([k, l]) => <button type="button" key={k} className={`chip-btn${filter === k ? " on" : ""}`} onClick={() => setFilter(k)}>{l}</button>)}
            </div>
            <DataTable rows={rows} rowKey={(p) => p.code} search exportName={`field_sales_${date}`} columns={[
              { header: "Employee", render: (p) => <button type="button" className="link-btn" onClick={() => setOpen(open === p.code ? null : p.code)}>
                  <strong>{p.name}</strong> <span className="muted">{p.code}</span>{open === p.code && p.evidence && <span className="sales-evidence">{p.evidence}</span>}</button>,
                value: (p) => `${p.name} ${p.code}` },
              { header: "Role", render: (p) => p.designation },
              { header: "Manager", render: (p) => p.manager },
              { header: "Status", render: (p) => <><StatusText s={p.status} label={p.status_label} />{p.leave && <div className="muted small">{p.leave}</div>}{p.not_marked && <div className="muted small">did not mark</div>}</>, value: (p) => p.status_label },
              { header: "Marked", render: (p) => p.att },
              { header: "Activity", render: (p) => (p.first ? `${p.first} – ${p.last}` : "") },
              { header: "In market", render: (p) => p.market, value: (p) => p.market_min },
              { header: "KM", render: (p) => p.km ?? "", value: (p) => p.km },
              { header: "Day end", render: (p) => p.eod },
              { header: "Warning signs", render: (p) => <Flags p={p} />, value: (p) => p.flags.map((f) => f.label).join("; ") },
            ]} />
          </Card>
        </>
      )}
    </>
  );
}

// ---------------------------------------------------------------- Approve emails
export function SalesMailPage() {
  const days = useApi<SalesDayRow[]>("/v1/sales/days");
  const [date, setDate] = useDayParam(days.data);
  const mail = useApi<SalesDayMail>(date ? `/v1/sales/days/${date}/mail` : null);
  const [preview, setPreview] = useState<number | null>(null);
  const { busy, error, message, run } = useAction();
  const ask = useConfirm();
  const { hasPermission } = useAuth();
  const canSend = hasPermission("UPLOAD_AND_SEND");
  const sendable = mail.data?.items.filter((i) => i.sendable) ?? [];
  useEffect(() => { setPreview(null); }, [date]);
  async function approveAll() {
    if (!date || !mail.data) return;
    const live = mail.data.mode === "live";
    if (!(await ask({ title: live ? "Send the emails?" : "Approve the emails?", confirmLabel: live ? "Send" : "Approve",
      message: live ? `${sendable.length} emails will be sent to the managers for ${formatDate(date)}.`
        : `Test mode: the ${sendable.length} emails are saved to the outbox, nothing is sent.`, danger: live }))) return;
    await run(() => api.post(`/v1/sales/days/${date}/mail/approve`, {}), live ? "Emails sent." : "Saved to the outbox (test mode).");
    mail.reload();
  }
  async function resend(id: number, name: string) {
    if (!(await ask({ title: "Send again?", message: `Send the email for ${name} again?`, confirmLabel: "Send again" }))) return;
    await run(() => api.post(`/v1/sales/mail/${id}/resend`), "Sent again.");
    mail.reload();
  }
  if (days.loading) return <Loading />;
  if (!days.data?.length) return <><PageHeader title="Approve emails" /><Notice>No Bizom day uploaded yet.</Notice></>;
  return (
    <>
      <PageHeader title="Approve emails" subtitle="One email per manager / zonal head / HOD, plus the Director and HR."
        actions={<Toolbar>
          <DayPicker days={days.data} date={date} onChange={setDate} />
          {canSend && <button type="button" className="btn btn-primary btn-auto" disabled={busy || sendable.length === 0} onClick={() => void approveAll()}>
            {mail.data?.mode === "live" ? "Approve & send" : "Approve (test)"} ({sendable.length})</button>}
        </Toolbar>} />
      {mail.data?.mode === "test" && <Notice kind="info">Field Sales email is in <b>test mode</b>: approved emails are saved to the outbox, not sent. Switch to live in Settings when approved.</Notice>}
      <ActionMessages error={error} message={message} />
      {mail.loading || !mail.data ? <Loading /> : (
        <div className={preview ? "grid-2 mail-split" : ""}>
          <Card>
            <DataTable rows={mail.data.items} rowKey={(i) => String(i.id)} search exportName={`field_sales_emails_${date}`} columns={[
              { header: "Recipient", render: (i) => <><strong>{i.name}</strong><div className="muted small">{i.role}</div></> , value: (i) => i.name },
              { header: "To", render: (i) => <span className="wrap-any">{i.to || "—"}</span> },
              { header: "People", render: (i) => i.counts.people ?? "" },
              { header: "Absent", render: (i) => i.counts.absent ?? "" },
              { header: "To check", render: (i) => i.counts.flagged ?? "" },
              { header: "Status", render: (i) => <><span className={`badge badge-${i.status === "FAILED" ? "fail" : i.status === "HELD" ? "warn" : ["SENT", "SAVED", "TEST_SENT"].includes(i.status) ? "ok" : "info"}`}>{i.status.replace("_", " ")}</span>
                {i.note && <div className="muted small">{i.note}</div>}</>, value: (i) => i.status },
              { header: "", sortable: false, render: (i) => <span className="row-actions">
                <button type="button" className="btn btn-ghost btn-small" onClick={() => setPreview(preview === i.id ? null : i.id)}>Preview</button>
                {canSend && ["SENT", "SAVED", "TEST_SENT", "DUPLICATE"].includes(i.status) && <button type="button" className="btn btn-ghost btn-small" onClick={() => void resend(i.id, i.name)}>Resend</button>}
              </span> },
            ]} />
          </Card>
          {preview && (
            <Card title="Preview" actions={<Toolbar>
              <a className="btn btn-ghost btn-small" href={apiUrl(`/v1/sales/mail/${preview}/attachment/excel`)}>Excel</a>
              <a className="btn btn-ghost btn-small" href={apiUrl(`/v1/sales/mail/${preview}/attachment/dashboard`)}>Dashboard</a>
              <button type="button" className="btn btn-ghost btn-small" onClick={() => setPreview(null)}>Close</button></Toolbar>}>
              <iframe className="email-frame" sandbox="" title="Email preview" src={apiUrl(`/v1/sales/mail/${preview}/preview`)} />
            </Card>
          )}
        </div>
      )}
    </>
  );
}

// ---------------------------------------------------------------- Staff list
export function SalesStaffPage() {
  const data = useApi<SalesStaff>("/v1/sales/staff");
  const { busy, error, message, run } = useAction();
  const { hasPermission } = useAuth();
  const canEdit = hasPermission("MANAGE_EMPLOYEES");
  async function importFile(f: File | undefined) {
    if (!f) return;
    const form = new FormData();
    form.append("file", f);
    await run(() => api.upload<{ added: number; updated: number; unchanged: number; problem_count: number }>("/v1/sales/staff/import", form),
      (r) => `Added ${r.added}, updated ${r.updated}, unchanged ${r.unchanged}${r.problem_count ? `, ${r.problem_count} problems` : ""}.`);
    data.reload();
  }
  const s = data.data?.summary;
  return (
    <>
      <PageHeader title="Field sales staff list" subtitle="Who should mark attendance in Bizom, and their managers' emails. Import adds and updates; it never deletes."
        actions={<Toolbar>
          {canEdit && <label className="btn btn-primary btn-auto">{busy ? "Importing…" : "Import staff list"}<input type="file" accept=".xlsx,.csv" hidden onChange={(e) => void importFile(e.target.files?.[0])} /></label>}
          <a className="btn btn-ghost btn-small" href={apiUrl("/v1/sales/staff/export")}>Export</a>
        </Toolbar>} />
      <ActionMessages error={error} message={message} />
      {data.error && <ErrorNotice error={data.error} />}
      {!s ? <Loading /> : (
        <>
          <div className="kpi-grid">
            <KpiCard label="Active staff" value={s.active} hint={`${s.left} left`} />
            <KpiCard label="With manager email" value={s.with_email.manager ?? 0} />
            <KpiCard label="With zonal head email" value={s.with_email.zonal ?? 0} />
            <KpiCard label="With HOD email" value={s.with_email.hod ?? 0} />
            <KpiCard label="No email route" value={s.no_route} tone={s.no_route ? "warn" : "ok"} hint="only in the Director / HR emails" />
          </div>
          <Card title="Staff">
            <DataTable rows={data.data?.staff ?? []} rowKey={(e) => e.code} search exportName="field_sales_staff" columns={[
              { header: "Code", render: (e) => e.code }, { header: "Name", render: (e) => <strong>{e.name}</strong>, value: (e) => e.name },
              { header: "Role", render: (e) => e.designation ?? "" }, { header: "Zone", render: (e) => e.zone ?? "" },
              { header: "Manager", render: (e) => <>{e.manager_name}{e.manager_email && <div className="muted small wrap-any">{e.manager_email}</div>}</>, value: (e) => e.manager_name },
              { header: "Zonal head", render: (e) => <>{e.zonal_name}{e.zonal_email && <div className="muted small wrap-any">{e.zonal_email}</div>}</>, value: (e) => e.zonal_name },
              { header: "HOD", render: (e) => <>{e.hod_name}{e.hod_email && <div className="muted small wrap-any">{e.hod_email}</div>}</>, value: (e) => e.hod_name },
              { header: "Status", render: (e) => <span className={`badge badge-${e.status === "ACTIVE" ? "ok" : "warn"}`}>{e.status}</span>, value: (e) => e.status },
            ]} />
          </Card>
        </>
      )}
    </>
  );
}

// ---------------------------------------------------------------- Settings
const LIST = (v: string) => v.split(/[,\n]/).map((x) => x.trim()).filter(Boolean);

export function SalesSettingsPage() {
  const data = useApi<{ rules: SalesRules; email: SalesEmailSettings }>("/v1/sales/settings");
  const [rules, setRules] = useState<SalesRules | null>(null);
  const [email, setEmail] = useState<SalesEmailSettings | null>(null);
  const { busy, error, message, run } = useAction();
  const ask = useConfirm();
  useEffect(() => { if (data.data) { setRules(data.data.rules); setEmail(data.data.email); } }, [data.data]);
  if (!rules || !email) return data.error ? <ErrorNotice error={data.error} /> : <Loading />;
  const num = (k: keyof SalesRules) => (
    <input type="number" value={rules[k] as number} onChange={(e) => setRules({ ...rules, [k]: Number(e.target.value) })} />
  );
  async function saveEmail() {
    if (email!.mode === "live" && data.data?.email.mode !== "live"
      && !(await ask({ title: "Switch to live?", message: "Approved Field Sales emails will really be sent to the managers.", confirmLabel: "Go live", danger: true }))) return;
    await run(() => api.put("/v1/sales/settings/email", email), "Email settings saved.");
    data.reload();
  }
  return (
    <>
      <PageHeader title="Field Sales settings" subtitle="Separate from Head Office settings." />
      <ActionMessages error={error} message={message} />
      <div className="grid-2">
        <Card title="Email" actions={<button type="button" className="btn btn-primary btn-small" disabled={busy} onClick={() => void saveEmail()}>Save</button>}>
          <Field label="Mode" hint="Test saves every email to the outbox; nothing is sent.">
            <select value={email.mode} onChange={(e) => setEmail({ ...email, mode: e.target.value as "test" | "live" })}>
              <option value="test">Test (saved, not sent)</option><option value="live">Live (sent)</option></select></Field>
          <Field label="Test recipient" hint="Optional: in testing, every email goes to this address instead.">
            <input value={email.test_recipient ?? ""} onChange={(e) => setEmail({ ...email, test_recipient: e.target.value || null })} /></Field>
          <Field label="Director name"><input value={email.director_name} onChange={(e) => setEmail({ ...email, director_name: e.target.value })} /></Field>
          <Field label="Director email(s)" hint="Comma separated. Empty = the Director's email is held.">
            <input value={email.director_emails.join(", ")} onChange={(e) => setEmail({ ...email, director_emails: LIST(e.target.value) })} /></Field>
          <Field label="HR email(s)"><input value={email.hr_emails.join(", ")} onChange={(e) => setEmail({ ...email, hr_emails: LIST(e.target.value) })} /></Field>
          <Field label="Always BCC"><input value={email.always_bcc.join(", ")} onChange={(e) => setEmail({ ...email, always_bcc: LIST(e.target.value) })} /></Field>
          <Field label="Team emails go to">
            <span className="check-row">{(["manager", "asm", "zonal", "hod"] as const).map((l) => (
              <label key={l} className="check"><input type="checkbox" checked={email.levels.includes(l)}
                onChange={(e) => setEmail({ ...email, levels: e.target.checked ? [...email.levels, l] : email.levels.filter((x) => x !== l) })} />
                {{ manager: "Managers", asm: "ASM / RSM", zonal: "Zonal heads", hod: "HODs" }[l]}</label>))}</span></Field>
        </Card>
        <Card title="Counting and warning signs" actions={<button type="button" className="btn btn-primary btn-small" disabled={busy}
          onClick={() => void run(() => api.put("/v1/sales/settings/rules", rules), "Rules saved. They apply to the next upload (upload again with replace to recount).")}>Save</button>}>
          <label className="check"><input type="checkbox" checked={rules.not_marked_is_absent} onChange={(e) => setRules({ ...rules, not_marked_is_absent: e.target.checked })} /> Staff who did not mark attendance count as absent</label>
          <label className="check"><input type="checkbox" checked={rules.include_promoters} onChange={(e) => setRules({ ...rules, include_promoters: e.target.checked })} /> Include promoters (AP codes)</label>
          <Field label="Supervisor roles (no market-activity checks)"><input value={rules.supervisor_designations.join(", ")} onChange={(e) => setRules({ ...rules, supervisor_designations: LIST(e.target.value) })} /></Field>
          <div className="form-grid">
            <Field label="Short time in market (minutes)">{num("short_market_minutes")}</Field>
            <Field label="Very short time in market (minutes)">{num("very_short_market_minutes")}</Field>
            <Field label="Late start: first activity after marking (minutes)">{num("late_start_minutes")}</Field>
            <Field label="Very high KM">{num("high_km")}</Field>
            <Field label="Attendance away from the spot (metres)">{num("attendance_far_m")}</Field>
            <Field label="Short day (minutes)">{num("short_day_minutes")}</Field>
            <Field label="Short visit (seconds)">{num("short_call_seconds")}</Field>
            <Field label="Visit away from the outlet (metres)">{num("far_call_m")}</Field>
            <Field label="Impossible travel speed (km/h)">{num("max_speed_kmh")}</Field>
            <Field label="Visits after (HH:MM)"><input value={rules.calls_after} onChange={(e) => setRules({ ...rules, calls_after: e.target.value })} /></Field>
          </div>
        </Card>
      </div>
    </>
  );
}
