import { useState } from "react";
import { api, apiUrl } from "../api/client";
import { useAction, useApi } from "../api/useApi";
import type { MailItem } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { useConfirm } from "../components/feedback";
import { ActionMessages, Card, DataTable, ErrorNotice, Field, Loading, Notice, PageHeader } from "../components/ui";
import { formatDate, formatDateTime } from "../format";

interface JobRun {
  id: number;
  job: string;
  target: string | null;
  trigger: string;
  status: "RUNNING" | "SUCCESS" | "PARTIAL" | "FAILED" | "SKIPPED";
  summary: Record<string, unknown> | null;
  error: string | null;
  started_by: string;
  started_at: string;
  finished_at: string | null;
  seconds: number | null;
}
interface JobsData {
  runs: JobRun[];
  inbox: string;
  yesterday: string;
  keep_months: number;
  backup_keep_days: number;
  database: string;
  previous_month: string;
}
interface MonthRow {
  month: string;
  label: string;
  days: number;
  employees: number;
  attendance_pct: string | null;
  status: string;
  archive: boolean;
  generated_at: string;
  generated_by: string;
  cleaned_at: string | null;
}
interface MonthDetail {
  month: string;
  label: string;
  status: string;
  items: MailItem[];
}
interface CleanupResult {
  status: "BLOCKED" | "PREVIEW" | "SUCCESS";
  problems?: string[];
  days?: number;
  rows_deleted?: number;
}

const KIND: Record<string, string> = { SUCCESS: "ok", PARTIAL: "warn", FAILED: "fail", RUNNING: "info", SKIPPED: "info" };

function details(r: JobRun): string {
  const s = r.summary ?? {};
  if (r.job === "DAILY") {
    const emails = s.emails as Record<string, number> | undefined;
    return [s.employees ? `${s.employees} employees` : "", Array.isArray(s.processed) && s.processed.length ? `${s.processed.length} new file(s)` : "",
      emails ? Object.entries(emails).map(([k, v]) => `${v} ${k.toLowerCase().replace("_", " ")}`).join(", ") : "", s.send_mode ? `(${s.send_mode})` : ""]
      .filter(Boolean).join(" · ");
  }
  if (r.job === "BACKUP" && s.bytes) return `${Math.round(Number(s.bytes) / 1024)} KB, integrity ${s.integrity}`;
  if (r.job === "MONTHLY" && s.days) return `${s.days} day(s), ${s.employees} employees, attendance ${s.attendance_pct}%`;
  if (r.job === "CLEANUP" && s.rows_deleted !== undefined) return `${s.rows_deleted} daily rows removed`;
  return "";
}

function MonthEmails({ month, canSend }: { month: string; canSend: boolean }) {
  const d = useApi<MonthDetail>(`/v1/monthly/${month}`);
  const act = useAction();
  if (d.loading) return <Loading />;
  if (d.error) return <ErrorNotice error={d.error} />;
  const items = d.data!.items;
  const pending = items.filter((i) => i.sendable);
  return (
    <Card title={`Monthly emails – ${d.data!.label}`}>
      <ActionMessages error={act.error} message={act.message} />
      {canSend && pending.length > 0 && (
        <button className="btn btn-primary btn-small" disabled={act.busy}
          onClick={() => void act.run(() => api.post<{ sent_now: number }>(`/v1/monthly/${month}/approve`, {}), (r) => `${r.sent_now} monthly email(s) sent.`).then((r) => r && d.reload())}>
          Approve & send all ({pending.length})
        </button>
      )}
      <DataTable rows={items} rowKey={(i) => String(i.id)} columns={[
        { header: "Recipient", render: (i) => <><strong>{i.name}</strong><br /><span className="muted small">{i.role}</span></> },
        { header: "To", render: (i) => <span className="small">{i.to || "—"}</span> },
        { header: "Employees", render: (i) => i.team },
        { header: "Need attention", render: (i) => i.attention },
        { header: "Status", render: (i) => <span className={`badge badge-${i.status === "SAVED" || i.status === "SENT" ? "ok" : i.status === "FAILED" || i.status === "HELD" ? "fail" : "warn"}`}>{i.status.replace("_", " ").toLowerCase()}</span> },
        { header: "", render: (i) => (
          <span className="inline-actions">
            <a className="btn btn-ghost btn-small" href={apiUrl(`/v1/mail/${i.id}/preview`)} target="_blank" rel="noreferrer">Preview</a>
            <a className="btn btn-ghost btn-small" href={apiUrl(`/v1/mail/${i.id}/attachment/excel`)}>Excel</a>
          </span>) },
      ]} />
    </Card>
  );
}

export function AutomationPage() {
  const data = useApi<JobsData>("/v1/jobs");
  const months = useApi<MonthRow[]>("/v1/monthly");
  const { hasPermission } = useAuth();
  const canSend = hasPermission("UPLOAD_AND_SEND");
  const isAdmin = hasPermission("MANAGE_SETTINGS");
  const [day, setDay] = useState("");
  const [dayMode, setDayMode] = useState<"manual" | "auto">("manual");
  const [month, setMonth] = useState("");
  const [monthMode, setMonthMode] = useState<"manual" | "auto">("manual");
  const [open, setOpen] = useState<string | null>(null);
  const [cleanup, setCleanup] = useState<Record<string, CleanupResult>>({});
  const act = useAction();
  const ask = useConfirm();

  if (data.loading && !data.data) return <Loading />;
  if (data.error) return <ErrorNotice error={data.error} />;
  const d = data.data!;
  const reloadAll = () => { data.reload(); months.reload(); };

  async function check(m: string, confirm: boolean) {
    if (confirm && !(await ask({ title: `Clean up ${m}?`, danger: true, confirmLabel: "Remove daily rows",
      message: `This permanently removes the daily attendance rows and stored files of ${m}. The monthly summary and archive stay. This cannot be undone.` }))) return;
    const r = await act.run(() => api.post<CleanupResult>(`/v1/monthly/${m}/cleanup`, { confirm }),
      (res) => (res.status === "SUCCESS" ? `${m}: ${res.rows_deleted} daily rows removed.` : res.status === "PREVIEW" ? `${m} can be cleaned.` : `${m} cannot be cleaned yet.`));
    if (r) { setCleanup({ ...cleanup, [m]: r }); reloadAll(); }
  }

  return (
    <>
      <PageHeader title="Automation" subtitle="Scheduled jobs (Windows Task Scheduler): 09:30 daily emails, backups, month-end reports and cleanup" />
      <Card title="How the daily job works">
        <p className="small">
          Every day at 09:30 the job takes <strong>yesterday's</strong> Pocket HRMS files from the inbox folder <code>{d.inbox}</code>,
          analyses them, checks every email can be built, and sends them (Auto) or prepares them for “Approve emails” (Manual, from Settings).
          Running it again never re-sends what already went out. Failures email an alert to the HR mailbox.
        </p>
        <p className="muted small">Database: {d.database} · backups kept {d.backup_keep_days} days · daily rows kept {d.keep_months} month(s), then archived and cleaned.</p>
      </Card>

      {canSend && (
        <Card title="Run now">
          <div className="filter-grid">
            <Field label="Day"><input type="date" value={day || d.yesterday} onChange={(e) => setDay(e.target.value)} /></Field>
            <Field label="Emails">
              <select value={dayMode} onChange={(e) => setDayMode(e.target.value as "manual" | "auto")}>
                <option value="manual">Manual – prepare for approval</option><option value="auto">Auto – send now</option>
              </select>
            </Field>
          </div>
          <div className="form-actions">
            <button className="btn btn-primary btn-small" disabled={act.busy}
              onClick={() => void act.run(() => api.post<{ status: string; problem?: string }>("/v1/jobs/daily", { report_date: day || d.yesterday, send_mode: dayMode }),
                (r) => `Daily job: ${r.status.toLowerCase()}${r.problem ? ` – ${r.problem}` : ""}`).then(reloadAll)}>Run daily job</button>
            {isAdmin && <button className="btn btn-ghost btn-small" disabled={act.busy}
              onClick={() => void act.run(() => api.post<{ file: string }>("/v1/jobs/backup"), (r) => `Backup saved: ${r.file}`).then(reloadAll)}>Back up database now</button>}
          </div>
          <ActionMessages error={act.error} message={act.message} />
        </Card>
      )}

      <Card title="Month-end">
        {canSend && (
          <>
            <div className="filter-grid">
              <Field label="Month"><input type="month" value={month || d.previous_month} onChange={(e) => setMonth(e.target.value)} /></Field>
              <Field label="Emails">
                <select value={monthMode} onChange={(e) => setMonthMode(e.target.value as "manual" | "auto")}>
                  <option value="manual">Manual – prepare for approval</option><option value="auto">Auto – send now</option>
                </select>
              </Field>
            </div>
            <div className="form-actions">
              <button className="btn btn-primary btn-small" disabled={act.busy}
                onClick={() => void act.run(() => api.post<{ status: string; problem?: string; emails?: Record<string, number> }>("/v1/monthly", { month: month || d.previous_month, send_mode: monthMode }),
                  (r) => `Monthly report: ${r.status.toLowerCase()}${r.problem ? ` – ${r.problem}` : ""}`).then((r) => { reloadAll(); if (r) setOpen(month || d.previous_month); })}>Generate monthly report</button>
            </div>
          </>
        )}
        {months.data && months.data.length === 0 && <p className="muted small">No monthly reports yet.</p>}
        {months.data && months.data.length > 0 && (
          <DataTable rows={months.data} rowKey={(m) => m.month} columns={[
            { header: "Month", render: (m) => <strong>{m.label}</strong> },
            { header: "Days", render: (m) => m.days },
            { header: "Employees", render: (m) => m.employees },
            { header: "Attendance", render: (m) => (m.attendance_pct ? `${m.attendance_pct}%` : "—") },
            { header: "Status", render: (m) => <span className={`badge badge-${m.status === "CLEANED" ? "info" : "ok"}`}>{m.status.toLowerCase()}</span> },
            { header: "Generated", render: (m) => <span className="small">{formatDateTime(m.generated_at)}</span> },
            { header: "", render: (m) => (
              <span className="inline-actions">
                <button className="btn btn-ghost btn-small" onClick={() => setOpen(open === m.month ? null : m.month)}>{open === m.month ? "Hide emails" : "Emails"}</button>
                {isAdmin && m.archive && <a className="btn btn-ghost btn-small" href={apiUrl(`/v1/monthly/${m.month}/archive`)}>Archive</a>}
                {isAdmin && m.status !== "CLEANED" && <button className="btn btn-ghost btn-small" onClick={() => void check(m.month, false)}>Check cleanup</button>}
                {isAdmin && cleanup[m.month]?.status === "PREVIEW" && <button className="btn btn-ghost btn-small danger" onClick={() => void check(m.month, true)}>Clean up</button>}
              </span>) },
          ]} />
        )}
        {Object.entries(cleanup).filter(([, r]) => r.status === "BLOCKED").map(([m, r]) => (
          <Notice key={m} kind="warn"><strong>{m} cannot be cleaned yet:</strong> {r.problems?.join(" ")}</Notice>
        ))}
      </Card>
      {open && <MonthEmails key={open} month={open} canSend={canSend} />}

      <Card title="Job history">
        <DataTable search exportName="job-history" rows={d.runs} rowKey={(r) => String(r.id)} columns={[
          { header: "Job", render: (r) => <strong>{r.job.toLowerCase()}</strong> },
          { header: "For", render: (r) => (r.target && r.target.length === 10 ? formatDate(r.target) : r.target ?? "") },
          { header: "Started", render: (r) => <span className="small">{formatDateTime(r.started_at)}</span> },
          { header: "By", render: (r) => <span className="small">{r.trigger.toLowerCase()} · {r.started_by}</span> },
          { header: "Status", render: (r) => <span className={`badge badge-${KIND[r.status] ?? "info"}`}>{r.status.toLowerCase()}</span> },
          { header: "Took", render: (r) => (r.seconds !== null ? `${r.seconds}s` : "") },
          { header: "Details", render: (r) => <span className="small">{r.error ?? details(r)}</span> },
        ]} />
        {d.runs.length === 0 && <p className="muted small">No jobs have run yet.</p>}
      </Card>
    </>
  );
}
