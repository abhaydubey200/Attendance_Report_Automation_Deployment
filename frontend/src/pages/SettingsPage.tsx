import { useState } from "react";
import { api } from "../api/client";
import { useAction, useApi } from "../api/useApi";
import type { EmailSettings, Rules, SettingsData } from "../api/types";
import { ActionMessages, Card, ErrorNotice, Field, Loading, Notice, PageHeader } from "../components/ui";

function RulesForm({ initial }: { initial: Rules }) {
  const [r, setR] = useState<Rules>(initial);
  const act = useAction();
  return (
    <Card title="How attendance is counted">
      <div className="form-grid">
        <Field label="Late if first punch after"><input type="time" value={r.late_after} onChange={(e) => setR({ ...r, late_after: e.target.value })} /></Field>
        <Field label="Left early if last punch before"><input type="time" value={r.early_before} onChange={(e) => setR({ ...r, early_before: e.target.value })} /></Field>
        <Field label="Short day: fewer hours than"><input type="number" step="0.5" min={0} max={24} value={r.min_work_hours} onChange={(e) => setR({ ...r, min_work_hours: Number(e.target.value) })} /></Field>
        <Field label="Long day: more hours than"><input type="number" step="0.5" min={0} max={24} value={r.long_work_hours} onChange={(e) => setR({ ...r, long_work_hours: Number(e.target.value) })} /></Field>
        <Field label="No punch, shift assigned">
          <select value={r.no_punch_with_shift} onChange={(e) => setR({ ...r, no_punch_with_shift: e.target.value as Rules["no_punch_with_shift"] })}>
            <option value="ABSENT">Absent</option><option value="NOT_TRACKED">Not tracked</option>
          </select>
        </Field>
        <Field label="No punch, no shift assigned" hint="Mostly field Sales staff">
          <select value={r.no_punch_no_shift} onChange={(e) => setR({ ...r, no_punch_no_shift: e.target.value as Rules["no_punch_no_shift"] })}>
            <option value="NOT_TRACKED">Not tracked (left out of %)</option><option value="ABSENT">Absent</option>
          </select>
        </Field>
        <Field label="Leave codes that mean on duty" hint="Comma separated, e.g. LD. Other codes count as leave.">
          <input value={r.on_duty_codes.join(", ")} onChange={(e) => setR({ ...r, on_duty_codes: e.target.value.split(",").map((x) => x.trim().toUpperCase()).filter(Boolean) })} />
        </Field>
        <Field label="Bizom-only users to include" hint="Besides the employee master. One per line (regular expressions); ^AP = promoters.">
          <textarea rows={2} value={(r.bizom_include_codes ?? []).join("\n")} onChange={(e) => setR({ ...r, bizom_include_codes: e.target.value.split("\n").map((x) => x.trim()).filter(Boolean) })} />
        </Field>
        <Field label="Skip these employee codes" hint="Test/dummy records. One per line (regular expressions).">
          <textarea rows={4} value={r.exclude_codes.join("\n")} onChange={(e) => setR({ ...r, exclude_codes: e.target.value.split("\n").map((x) => x.trim()).filter(Boolean) })} />
        </Field>
      </div>
      <label className="check"><input type="checkbox" checked={r.single_punch_counts_present} onChange={(e) => setR({ ...r, single_punch_counts_present: e.target.checked })} /> Count a single punch as present (still listed as missing punch)</label>
      <ActionMessages error={act.error} message={act.message} />
      <div className="form-actions">
        <button className="btn btn-primary btn-inline" disabled={act.busy}
          onClick={() => void act.run(() => api.put("/v1/settings/rules", r), "Saved. New uploads use these rules; to apply them to an existing day, upload it again with Replace.")}>Save rules</button>
      </div>
    </Card>
  );
}

const list = (v: string) => v.split(/[,;\s]+/).map((x) => x.trim()).filter(Boolean);

function Check({ on, set, children }: { on: boolean; set: (v: boolean) => void; children: string }) {
  return <label className="check"><input type="checkbox" checked={on} onChange={(x) => set(x.target.checked)} /> {children}</label>;
}

function EmailForm({ initial, secrets }: { initial: EmailSettings; secrets: Record<string, boolean> }) {
  const [e, setE] = useState<EmailSettings>(initial);
  const [director, setDirector] = useState(initial.director_emails.join(", "));
  const [hr, setHr] = useState(initial.hr_emails.join(", "));
  const [to, setTo] = useState("");
  const act = useAction();
  const test = useAction();
  const set = (patch: Partial<EmailSettings>) => setE({ ...e, ...patch });
  const needed = e.provider === "smtp" ? ["SMTP_PASSWORD"] : e.provider === "graph" ? ["GRAPH_TENANT_ID", "GRAPH_CLIENT_ID", "GRAPH_CLIENT_SECRET"]
    : ["GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET", "GMAIL_REFRESH_TOKEN"];
  return (
    <>
      <Card title="Who gets the daily emails">
        <p className="muted small">Team leads (Sub split ID) and HODs come from the employee master on the Employees screen. One email per person per day.</p>
        <div className="form-grid">
          <Field label="Director name"><input value={e.director_name} onChange={(x) => set({ director_name: x.target.value })} /></Field>
          <Field label="Director email(s)" hint="Company summary by HOD + Director Office staff. Comma separated.">
            <input value={director} onChange={(x) => setDirector(x.target.value)} placeholder="director@apisindia.com" />
          </Field>
          <Field label="HR attendance mailbox" hint="Gets records that cannot be routed (only on days with any).">
            <input value={hr} onChange={(x) => setHr(x.target.value)} placeholder="hr.attendance@apisindia.com" />
          </Field>
        </div>
        <Check on={e.team_emails} set={(v) => set({ team_emails: v })}>Team leads get their own team's attendance</Check>
        <Check on={e.hod_summary} set={(v) => set({ hod_summary: v })}>HODs get a summary of everyone under them</Check>
        <Check on={e.director_report} set={(v) => set({ director_report: v })}>Director gets the company summary</Check>
        <Check on={e.hr_exceptions} set={(v) => set({ hr_exceptions: v })}>HR gets the exception report</Check>
        <Check on={e.hod_cc_on_team} set={(v) => set({ hod_cc_on_team: v })}>CC the HOD on team-lead emails (only if HR has approved)</Check>
        <Check on={e.hr_cc_on_hod_summary} set={(v) => set({ hr_cc_on_hod_summary: v })}>CC the HR mailbox on HOD summaries</Check>
      </Card>
      <Card title="Sending">
        <Check on={e.approval_required} set={(v) => set({ approval_required: v })}>Preview mode: emails wait on “Approve emails” until someone approves them</Check>
        {!e.approval_required && <Check on={e.auto_send} set={(v) => set({ auto_send: v })}>Send automatically right after each upload</Check>}
        <Check on={e.wait_for_bizom} set={(v) => set({ wait_for_bizom: v })}>Prepare the emails only once both the Pocket HRMS and the Bizom file of the day are uploaded</Check>
        <Check on={e.attach_excel} set={(v) => set({ attach_excel: v })}>Attach the team list (.xlsx)</Check>
        <Check on={e.attach_dashboard} set={(v) => set({ attach_dashboard: v })}>Attach the interactive HTML dashboard</Check>
        <div className="form-grid">
          <Field label="Mode">
            <select value={e.mode} onChange={(x) => set({ mode: x.target.value as EmailSettings["mode"] })}>
              <option value="test">Test – save emails to the outbox, don't deliver</option><option value="live">Live – deliver</option>
            </select>
          </Field>
          <Field label="Mail provider">
            <select value={e.provider} onChange={(x) => set({ provider: x.target.value as EmailSettings["provider"] })}>
              <option value="smtp">SMTP (any mail server)</option><option value="graph">Microsoft 365 (Graph API)</option><option value="gmail">Google Workspace (Gmail API)</option>
            </select>
          </Field>
          <Field label="Sender mailbox" hint="One central company mailbox, e.g. attendance@…"><input value={e.sender ?? ""} onChange={(x) => set({ sender: x.target.value || null })} placeholder="attendance@apisindia.com" /></Field>
          <Field label="Reply-to (optional)"><input value={e.reply_to ?? ""} onChange={(x) => set({ reply_to: x.target.value || null })} /></Field>
          {e.provider === "smtp" && (
            <>
              <Field label="SMTP server" hint="Microsoft 365: smtp.office365.com"><input value={e.smtp_host ?? ""} onChange={(x) => set({ smtp_host: x.target.value || null })} /></Field>
              <Field label="Port"><input type="number" value={e.smtp_port} onChange={(x) => set({ smtp_port: Number(x.target.value) })} /></Field>
              <Field label="SMTP username"><input value={e.smtp_username ?? ""} onChange={(x) => set({ smtp_username: x.target.value || null })} /></Field>
            </>
          )}
          <Field label="Subject starts with"><input value={e.subject_prefix} onChange={(x) => set({ subject_prefix: x.target.value })} /></Field>
          <Field label="Attempts per email" hint="Retries with a short pause if delivery fails.">
            <input type="number" min={1} max={5} value={e.retry_attempts} onChange={(x) => set({ retry_attempts: Number(x.target.value) })} />
          </Field>
        </div>
        {e.provider === "smtp" && <Check on={e.smtp_starttls} set={(v) => set({ smtp_starttls: v })}>Use STARTTLS (encrypted connection)</Check>}
        <p className="muted small">
          Secrets for {e.provider === "smtp" ? "SMTP" : e.provider === "graph" ? "Microsoft Graph" : "Gmail"} come only from the server's .env file:{" "}
          {needed.map((n) => `${n} ${secrets[n] ? "✓ set" : "✗ not set"}`).join(" · ")}. They are never stored in the app.
        </p>
        <ActionMessages error={act.error} message={act.message} />
        <div className="form-actions">
          <button className="btn btn-primary btn-inline" disabled={act.busy}
            onClick={() => void act.run(() => api.put("/v1/settings/email", { ...e, director_emails: list(director), hr_emails: list(hr) }), "Email settings saved.")}>Save email settings</button>
        </div>
        <div className="toolbar" style={{ marginTop: "1rem" }}>
          <Field label="Send a test email to"><input type="email" value={to} onChange={(x) => setTo(x.target.value)} placeholder="you@apisindia.com" /></Field>
          <button className="btn btn-ghost btn-inline" disabled={test.busy || !to}
            onClick={() => void test.run(() => api.post<{ status: string; mode: string }>("/v1/settings/test-email", { to }),
              (r) => (r.status === "SENT" ? "Test email sent." : "Test mode: saved to the outbox (not sent)."))}>Send test</button>
        </div>
        <ActionMessages error={test.error} message={test.message} />
      </Card>
    </>
  );
}

export function SettingsPage() {
  const data = useApi<SettingsData>("/v1/settings");
  return (
    <>
      <PageHeader title="Settings" subtitle="Who gets the emails, how they are sent, and how attendance is counted" />
      {data.loading && <Loading />}
      {data.error && <ErrorNotice error={data.error} />}
      {data.data && (
        <>
          {data.data.email.mode === "test" && <Notice kind="warn">Email is in test mode: emails are prepared and saved to the outbox, but not delivered.</Notice>}
          <EmailForm key={JSON.stringify(data.data.email)} initial={data.data.email} secrets={data.data.secrets ?? {}} />
          <RulesForm initial={data.data.rules} />
        </>
      )}
    </>
  );
}
