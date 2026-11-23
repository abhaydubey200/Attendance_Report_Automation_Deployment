import { useState } from "react";
import { api } from "../api/client";
import { useAction, useApi } from "../api/useApi";
import type { EmailSettings, Rules, SettingsData } from "../api/types";
import { formatTime } from "../format";
import { ActionMessages, Card, ErrorNotice, Field, Loading, Notice, PageHeader } from "../components/ui";
import { HolidayListCard } from "../components/HolidayListCard";

function RulesForm({ initial }: { initial: Rules }) {
  const [r, setR] = useState<Rules>(initial);
  const act = useAction();
  return (
    <Card title="How attendance is counted">
      <div className="form-grid">
        <Field label={`Office opens (${formatTime(r.late_after)})`} hint="Arriving from this time up to the latest punch-in is on time."><input type="time" value={r.late_after} onChange={(e) => setR({ ...r, late_after: e.target.value })} /></Field>
        <Field label={`Latest punch-in, late after (${formatTime(r.flexi_until) || "not set"})`} hint="A first punch after this is late; late minutes are counted from this time. Empty = late after the opening time.">
          <input type="time" value={r.flexi_until ?? ""} onChange={(e) => setR({ ...r, flexi_until: e.target.value || null })} />
        </Field>
        <Field label={`Office closes (${formatTime(r.early_before)})`} hint="Leaving before this without completing the mandatory hours = left early."><input type="time" value={r.early_before} onChange={(e) => setR({ ...r, early_before: e.target.value })} /></Field>
        <Field label="Mandatory hours" hint="Every employee must work this long, counted from their own punch-in to punch-out. Less = short hours."><input type="number" step="0.5" min={0} max={24} value={r.min_work_hours} onChange={(e) => setR({ ...r, min_work_hours: Number(e.target.value) })} /></Field>
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
        <Field label="Always counted as present" hint="Employee codes, one per line (the Directors). Never marked absent, late, left early or missing punch.">
          <textarea rows={3} value={(r.always_present_codes ?? []).join("\n")} onChange={(e) => setR({ ...r, always_present_codes: e.target.value.split("\n").map((x) => x.trim().toUpperCase()).filter(Boolean) })} />
        </Field>
        <Field label="Leave out these categories (if not in the employee master)" hint="Pocket HRMS categories handled elsewhere, one per line. Default Sales: field sales staff are covered by the Bizom tool.">
          <textarea rows={2} value={(r.out_of_scope_categories ?? []).join("\n")} onChange={(e) => setR({ ...r, out_of_scope_categories: e.target.value.split("\n").map((x) => x.trim()).filter(Boolean) })} />
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
  const [alwaysBcc, setAlwaysBcc] = useState((initial.always_bcc ?? []).join(", "));
  const [testCc, setTestCc] = useState((initial.test_cc ?? []).join(", "));
  const [to, setTo] = useState("");
  const act = useAction();
  const test = useAction();
  const set = (patch: Partial<EmailSettings>) => setE({ ...e, ...patch });
  const needed = ["GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET", "GMAIL_REFRESH_TOKEN"];
  return (
    <>
      <Card title="Who gets the daily emails">
        <p className="muted small">HODs come from the employee master on the Employees screen. One email per HOD per day, covering everyone under them.</p>
        <div className="form-grid">
          <Field label="Director name"><input value={e.director_name} onChange={(x) => set({ director_name: x.target.value })} /></Field>
          <Field label="Director email(s)" hint="Company summary by HOD + Director Office staff. Comma separated.">
            <input value={director} onChange={(x) => setDirector(x.target.value)} placeholder="director@apisindia.com" />
          </Field>
          <Field label="HR attendance mailbox" hint="Gets records that cannot be routed (only on days with any).">
            <input value={hr} onChange={(x) => setHr(x.target.value)} placeholder="hr.attendance@apisindia.com" />
          </Field>
          <Field label="Always BCC (every email)" hint="Blind copy of every daily and month-end email – recipients do not see it. Comma separated.">
            <input value={alwaysBcc} onChange={(x) => setAlwaysBcc(x.target.value)} placeholder="hr.head@apisindia.com" />
          </Field>
        </div>
        <Check on={e.team_emails} set={(v) => set({ team_emails: v })}>Team leads get their own team's attendance</Check>
        <Check on={e.hod_summary} set={(v) => set({ hod_summary: v })}>HODs get a summary of everyone under them</Check>
        <Check on={e.director_report} set={(v) => set({ director_report: v })}>Director gets the company summary</Check>
        <Check on={e.hr_exceptions} set={(v) => set({ hr_exceptions: v })}>HR gets the exception report</Check>
        <Check on={e.hod_cc_on_team} set={(v) => set({ hod_cc_on_team: v })}>CC the HOD on team-lead emails (only if HR has approved)</Check>
        <Check on={e.hr_cc_on_hod_summary} set={(v) => set({ hr_cc_on_hod_summary: v })}>CC the HR mailbox on HOD summaries</Check>
      </Card>
      <Card title="Testing">
        <Field label="Send every email only to (testing)" hint="Every email – team leads, HODs, Director, HR – goes ONLY to this address, marked [TEST] with the real recipient shown inside. Leave empty for normal sending.">
          <input type="email" value={e.test_recipient ?? ""} onChange={(x) => set({ test_recipient: x.target.value || null })} placeholder="you@apisindia.com" />
        </Field>
        <Field label="CC on test emails (optional)" hint="Comma separated.">
          <input value={testCc} onChange={(x) => setTestCc(x.target.value)} placeholder="colleague@apisindia.com" disabled={!e.test_recipient} />
        </Field>
        {e.test_recipient && <Notice kind="warn">Testing is ON: nobody else will receive the daily emails until this field is cleared and saved.</Notice>}
      </Card>
      <Card title="Sending (Gmail API)">
        <Check on={e.approval_required} set={(v) => set({ approval_required: v })}>Preview mode: emails wait on “Approve emails” until someone approves them</Check>
        {!e.approval_required && <Check on={e.auto_send} set={(v) => set({ auto_send: v })}>Send automatically right after each upload</Check>}
        <Check on={e.wait_for_permission} set={(v) => set({ wait_for_permission: v })}>Prepare the emails only once the day's Permission Report is uploaded too</Check>
        <Check on={e.attach_excel} set={(v) => set({ attach_excel: v })}>Attach the team list (.xlsx)</Check>
        <Check on={e.attach_dashboard} set={(v) => set({ attach_dashboard: v })}>Attach the interactive HTML dashboard</Check>
        <div className="form-grid">
          <Field label="Mode">
            <select value={e.mode} onChange={(x) => set({ mode: x.target.value as EmailSettings["mode"] })}>
              <option value="test">Test – save emails to the outbox, don't send</option><option value="live">Live – send through the Gmail API</option>
            </select>
          </Field>
          <Field label="Sender mailbox" hint="The Gmail / Google Workspace mailbox signed in with main.py gmail-auth."><input value={e.sender ?? ""} onChange={(x) => set({ sender: x.target.value || null })} placeholder="attendance@apisindia.com" /></Field>
          <Field label="Reply-to (optional)"><input value={e.reply_to ?? ""} onChange={(x) => set({ reply_to: x.target.value || null })} /></Field>
          <Field label="Subject starts with"><input value={e.subject_prefix} onChange={(x) => set({ subject_prefix: x.target.value })} /></Field>
          <Field label="Attempts per email" hint="Retries with a short pause if delivery fails.">
            <input type="number" min={1} max={5} value={e.retry_attempts} onChange={(x) => set({ retry_attempts: Number(x.target.value) })} />
          </Field>
        </div>
        <p className="muted small">
          Gmail API secrets come only from the server's .env file:{" "}
          {needed.map((n) => `${n} ${secrets[n] ? "✓ set" : "✗ not set"}`).join(" · ")}. They are never stored in the app.
        </p>
        <ActionMessages error={act.error} message={act.message} />
        <div className="form-actions">
          <button className="btn btn-primary btn-inline" disabled={act.busy}
            onClick={() => void act.run(() => api.put("/v1/settings/email", { ...e, director_emails: list(director), hr_emails: list(hr), always_cc: [], always_bcc: list(alwaysBcc), test_cc: list(testCc) }), "Email settings saved.")}>Save email settings</button>
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
          <HolidayListCard module="head-office" />
        </>
      )}
    </>
  );
}
