import { useState } from "react";
import { api } from "../api/client";
import { useAction, useApi } from "../api/useApi";
import type { EmailSettings, RecipientRow, Rules, SettingsData } from "../api/types";
import { ActionMessages, Card, ErrorNotice, Field, Loading, Notice, PageHeader } from "../components/ui";

function Recipients({ initial, categories, onSaved }: { initial: RecipientRow[]; categories: string[]; onSaved: () => void }) {
  const [rows, setRows] = useState<RecipientRow[]>(initial.length ? initial : [{ name: "", email: "", scope: "ALL", active: true }]);
  const act = useAction();
  const scopes = ["ALL", ...categories];
  const set = (i: number, patch: Partial<RecipientRow>) => setRows(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  const missing = categories.filter((c) => !rows.some((r) => r.scope === c && r.email));
  return (
    <Card title="Who gets the reports">
      <p className="muted small">Each team's manager gets that team's report. “All employees” is the full company report (HR, Directors).</p>
      <table className="edit-table">
        <thead><tr><th>Name</th><th>Email</th><th>Receives report for</th><th>Active</th><th /></tr></thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              <td><input value={r.name} onChange={(e) => set(i, { name: e.target.value })} placeholder="e.g. Sales Manager" /></td>
              <td><input type="email" value={r.email} onChange={(e) => set(i, { email: e.target.value })} placeholder="name@apisindia.com" /></td>
              <td>
                <select value={r.scope} onChange={(e) => set(i, { scope: e.target.value })}>
                  {[...new Set([...scopes, r.scope])].map((s) => <option key={s} value={s}>{s === "ALL" ? "All employees" : s}</option>)}
                </select>
              </td>
              <td><input type="checkbox" checked={r.active} onChange={(e) => set(i, { active: e.target.checked })} /></td>
              <td><button className="btn btn-ghost btn-small" onClick={() => setRows(rows.filter((_, j) => j !== i))}>Remove</button></td>
            </tr>
          ))}
        </tbody>
      </table>
      {missing.length > 0 && <p className="muted small">No manager yet for: {missing.join(", ")}.</p>}
      <ActionMessages error={act.error} message={act.message} />
      <div className="form-actions">
        <button className="btn btn-ghost btn-inline" onClick={() => setRows([...rows, { name: "", email: "", scope: missing[0] ?? "ALL", active: true }])}>Add person</button>
        <button className="btn btn-primary btn-inline" disabled={act.busy}
          onClick={() => void act.run(() => api.put("/v1/settings/recipients", { recipients: rows }), "Recipients saved.").then((r) => r && onSaved())}>Save recipients</button>
      </div>
    </Card>
  );
}

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

function EmailForm({ initial, passwordSet }: { initial: EmailSettings; passwordSet: boolean }) {
  const [e, setE] = useState<EmailSettings>(initial);
  const [to, setTo] = useState("");
  const act = useAction();
  const test = useAction();
  return (
    <Card title="Email">
      <div className="form-grid">
        <Field label="Mode">
          <select value={e.mode} onChange={(x) => setE({ ...e, mode: x.target.value as EmailSettings["mode"] })}>
            <option value="test">Test – save emails, don't send</option><option value="live">Live – send to managers</option>
          </select>
        </Field>
        <Field label="Sender address"><input value={e.sender ?? ""} onChange={(x) => setE({ ...e, sender: x.target.value || null })} placeholder="hr-reports@apisindia.com" /></Field>
        <Field label="SMTP server" hint="Microsoft 365: smtp.office365.com"><input value={e.smtp_host ?? ""} onChange={(x) => setE({ ...e, smtp_host: x.target.value || null })} /></Field>
        <Field label="Port"><input type="number" value={e.smtp_port} onChange={(x) => setE({ ...e, smtp_port: Number(x.target.value) })} /></Field>
        <Field label="SMTP username"><input value={e.smtp_username ?? ""} onChange={(x) => setE({ ...e, smtp_username: x.target.value || null })} /></Field>
        <Field label="Subject starts with"><input value={e.subject_prefix} onChange={(x) => setE({ ...e, subject_prefix: x.target.value })} /></Field>
      </div>
      <label className="check"><input type="checkbox" checked={e.auto_send} onChange={(x) => setE({ ...e, auto_send: x.target.checked })} /> Send automatically after each upload</label>
      <label className="check"><input type="checkbox" checked={e.smtp_starttls} onChange={(x) => setE({ ...e, smtp_starttls: x.target.checked })} /> Use STARTTLS (encrypted connection)</label>
      <label className="check"><input type="checkbox" checked={e.attach_excel} onChange={(x) => setE({ ...e, attach_excel: x.target.checked })} /> Attach Excel report</label>
      <label className="check"><input type="checkbox" checked={e.attach_dashboard} onChange={(x) => setE({ ...e, attach_dashboard: x.target.checked })} /> Attach HTML dashboard</label>
      <p className="muted small">SMTP password: {passwordSet ? "set (environment variable SMTP_PASSWORD)" : "not set – put SMTP_PASSWORD in the .env file on the server; it is never stored in the app."}</p>
      <ActionMessages error={act.error} message={act.message} />
      <div className="form-actions">
        <button className="btn btn-primary btn-inline" disabled={act.busy} onClick={() => void act.run(() => api.put("/v1/settings/email", e), "Email settings saved.")}>Save email settings</button>
      </div>
      <div className="toolbar" style={{ marginTop: "1rem" }}>
        <Field label="Send a test email to"><input type="email" value={to} onChange={(x) => setTo(x.target.value)} placeholder="you@apisindia.com" /></Field>
        <button className="btn btn-ghost btn-inline" disabled={test.busy || !to}
          onClick={() => void test.run(() => api.post<{ status: string; mode: string }>("/v1/settings/test-email", { to }),
            (r) => (r.status === "SENT" ? "Test email sent." : "Test mode: saved to the outbox (not sent)."))}>Send test</button>
      </div>
      <ActionMessages error={test.error} message={test.message} />
    </Card>
  );
}

export function SettingsPage() {
  const data = useApi<SettingsData>("/v1/settings");
  return (
    <>
      <PageHeader title="Settings" subtitle="Recipients, counting rules and email" />
      {data.loading && <Loading />}
      {data.error && <ErrorNotice error={data.error} />}
      {data.data && (
        <>
          {data.data.email.mode === "test" && <Notice kind="warn">Email is in test mode: reports are prepared and saved, but not sent.</Notice>}
          <Recipients key={JSON.stringify(data.data.recipients)} initial={data.data.recipients} categories={data.data.categories} onSaved={data.reload} />
          <RulesForm initial={data.data.rules} />
          <EmailForm initial={data.data.email} passwordSet={data.data.smtp_password_set} />
        </>
      )}
    </>
  );
}
