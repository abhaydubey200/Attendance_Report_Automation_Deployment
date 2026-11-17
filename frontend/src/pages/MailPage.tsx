import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, apiUrl } from "../api/client";
import { useAction, useApi } from "../api/useApi";
import type { DayListItem, DayMail, MailItem, MailStatus, RoutingOverview } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { ActionMessages, Card, DataTable, ErrorNotice, Field, KpiCard, Loading, Notice, PageHeader, Toolbar } from "../components/ui";
import { formatDate, formatDateTime } from "../format";

const STATUS_TEXT: Record<MailStatus, [string, string]> = {
  PENDING: ["Waiting for approval", "warn"],
  SENT: ["Sent", "ok"],
  SAVED: ["Saved (test mode)", "ok"],
  FAILED: ["Failed", "fail"],
  HELD: ["Held", "fail"],
  DISABLED: ["Switched off", "info"],
  DUPLICATE: ["Already sent for this day", "info"],
  SUPERSEDED: ["Replaced", "info"],
  TEST_SENT: ["Sent to test address", "warn"],
};

function MailBadge({ status }: { status: MailStatus }) {
  const [text, kind] = STATUS_TEXT[status] ?? [status, "info"];
  return <span className={`badge badge-${kind}`}>{text}</span>;
}

function what(i: MailItem): string {
  if (i.key === "HR") return `${i.exceptions} record(s) to fix`;
  const parts = [];
  if (i.company) parts.push(`company ${i.company}`);
  if (i.team) parts.push(`${i.company ? "staff" : "team"} ${i.team}`);
  if (i.summary) parts.push(`department ${i.summary}`);
  return parts.join(" + ") || "—";
}

function RoutingCheck({ canEdit }: { canEdit: boolean }) {
  const r = useApi<RoutingOverview>("/v1/routing");
  const act = useAction();
  if (r.loading) return <Loading />;
  if (r.error) return <ErrorNotice error={r.error} />;
  const o = r.data!;
  async function toggle(email: string, active: boolean) {
    const res = await act.run(() => api.put("/v1/routing/recipients", { email, active }));
    if (res) r.reload();
  }
  return (
    <Card title="Routing check (from the employee master)">
      <p className="muted small">
        {o.employees} active employees · {o.routed_to_people} go to a team lead or HOD · {o.routed_to_director} to the Director ·{" "}
        {o.held.length} held for HR · each employee counted once: {o.unique && o.detail_total === o.employees ? "yes ✓" : "NO – check the master"}.
        Change routing on the <Link to="/employees">Employees</Link> screen or re-import the routing workbook.
      </p>
      <ActionMessages error={act.error} message={null} />
      <DataTable rows={o.recipients} rowKey={(x) => x.key} columns={[
        { header: "Recipient", render: (x) => <strong>{x.name}</strong> },
        { header: "Role", render: (x) => x.role },
        { header: "To", render: (x) => x.to.join(", ") || "—" },
        { header: "Team detail", render: (x) => x.team },
        { header: "Department summary", render: (x) => x.summary || "" },
        { header: "Status", render: (x) => (x.status === "OK" ? <span className="badge badge-ok">Will be sent</span>
          : <span className={`badge badge-${x.status === "HELD" ? "fail" : "info"}`} title={x.note ?? ""}>{x.status === "HELD" ? "Held" : "Switched off"}</span>) },
        { header: "Note", render: (x) => <span className="small">{x.note ?? ""}</span> },
        ...(canEdit ? [{ header: "", render: (x: RoutingOverview["recipients"][number]) => (x.key.includes("@")
          ? <button className="btn btn-ghost btn-small" disabled={act.busy} onClick={() => void toggle(x.key, x.status === "DISABLED")}>
              {x.status === "DISABLED" ? "Switch on" : "Switch off"}</button> : null) }] : []),
      ]} />
      {o.held.length > 0 && (
        <>
          <h4>Held for HR (never sent to an assumed person)</h4>
          <DataTable rows={o.held} rowKey={(h) => h.code} columns={[
            { header: "Code", render: (h) => h.code },
            { header: "Name", render: (h) => h.name },
            { header: "Department", render: (h) => h.department },
            { header: "HOD", render: (h) => h.hod },
            { header: "Issue", render: (h) => h.issue ?? "" },
          ]} />
        </>
      )}
    </Card>
  );
}

export function MailPage() {
  const [params, setParams] = useSearchParams();
  const days = useApi<DayListItem[]>("/v1/days");
  const date = params.get("date") || days.data?.[0]?.report_date || "";
  const day = useApi<DayMail>(date ? `/v1/days/${date}/mail` : null);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [preview, setPreview] = useState<MailItem | null>(null);
  const [view, setView] = useState<"day" | "routing">("day");
  const act = useAction();
  const { hasPermission } = useAuth();
  const canSend = hasPermission("UPLOAD_AND_SEND");
  const isAdmin = hasPermission("MANAGE_SETTINGS");

  useEffect(() => { setSelected(new Set()); setPreview(null); }, [date]);

  const items = day.data?.items ?? [];
  const pending = items.filter((i) => i.sendable);
  const testing = day.data?.test_recipient;
  const count = (s: MailStatus) => day.data?.status[s] ?? 0;

  async function approve(ids: number[] | null) {
    const n = ids ? ids.length : pending.length;
    const r = await act.run(() => api.post<DayMail>(`/v1/days/${date}/mail/approve`, { ids }),
      (res) => `${res.sent_now ?? 0} of ${n} email(s) ${day.data?.mode === "test" ? "saved to the outbox (test mode)" : "sent"}.`);
    if (r) { setSelected(new Set()); day.reload(); }
  }
  async function replan() {
    const r = await act.run(() => api.post<DayMail>(`/v1/days/${date}/mail/plan`), "Emails prepared again from the current employee master.");
    if (r) day.reload();
  }
  async function resend(i: MailItem) {
    if (!window.confirm(`Send ${i.name} the email for ${formatDate(i.report_date)} again? They already received it.`)) return;
    const r = await act.run(() => api.post<MailItem>(`/v1/mail/${i.id}/resend`), `Sent again to ${i.name}.`);
    if (r) day.reload();
  }
  const toggle = (id: number) => {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id); else next.add(id);
    setSelected(next);
  };

  return (
    <>
      <PageHeader title="Daily emails" subtitle="One email per HOD, plus the Director and the HR exception report. Check, then approve." />
      <Toolbar>
        <Field label="Day">
          <select value={date} onChange={(e) => setParams({ date: e.target.value })}>
            {days.data?.map((d) => <option key={d.report_date} value={d.report_date}>{formatDate(d.report_date)}</option>)}
          </select>
        </Field>
        <div className="chips">
          <button className={`chip${view === "day" ? " on" : ""}`} onClick={() => setView("day")}>Emails of the day</button>
          <button className={`chip${view === "routing" ? " on" : ""}`} onClick={() => setView("routing")}>Routing check</button>
        </div>
        {view === "day" && canSend && date && (
          <div className="toolbar-actions">
            <button className="btn btn-ghost btn-inline" disabled={act.busy} onClick={() => void replan()}>Prepare again</button>
            {selected.size > 0 && <button className="btn btn-ghost btn-inline" disabled={act.busy} onClick={() => void approve([...selected])}>Approve selected ({selected.size})</button>}
            <button className="btn btn-primary btn-inline" disabled={act.busy || !pending.length} onClick={() => void approve(null)}>
              {act.busy ? "Sending…" : testing ? `Send all to test address (${pending.length})` : `Approve & send all (${pending.length})`}
            </button>
          </div>
        )}
      </Toolbar>
      <ActionMessages error={act.error} message={act.message} />

      {view === "routing" && <RoutingCheck canEdit={isAdmin} />}

      {view === "day" && (
        <>
          {days.data && !days.data.length && <Notice>No day uploaded yet. Start on the <Link to="/upload">Upload</Link> page.</Notice>}
          {day.error && <ErrorNotice error={day.error} />}
          {day.loading && !day.data && <Loading />}
          {day.data && (
            <>
              {testing && (
                <Notice kind="fail">
                  <strong>Testing:</strong> every email goes ONLY to <strong>{testing}</strong>{day.data.test_cc?.length ? <> (CC <strong>{day.data.test_cc.join(", ")}</strong>)</> : null}, marked [TEST] and showing who would normally get it.
                  The real managers receive nothing until the test address is cleared in <Link to="/settings">Settings</Link>.
                </Notice>
              )}
              {day.data.mode === "test" && <Notice kind="warn">Test mode: approved emails are saved to the outbox folder, not delivered. Switch to live in <Link to="/settings">Settings</Link>.</Notice>}
              {!day.data.planned && <Notice>No emails prepared for this day yet{canSend ? " – they are prepared after the upload (once both files are in), or use “Prepare again”." : "."}</Notice>}
              {day.data.planned && (
                <div className="kpi-grid">
                  <KpiCard label="Emails" value={items.length} />
                  <KpiCard label="Waiting for approval" value={count("PENDING")} />
                  <KpiCard label={day.data.mode === "test" ? "Saved (test)" : "Sent"} value={count("SENT") + count("SAVED")} />
                  <KpiCard label="Failed" value={count("FAILED")} />
                  <KpiCard label="Held" value={count("HELD")} />
                  <KpiCard label="Already sent / off" value={count("DUPLICATE") + count("DISABLED")} />
                </div>
              )}
              {count("HELD") > 0 && <Notice kind="warn">Held emails have no valid address (e.g. Director or HR mailbox not set in Settings). They are not sent.</Notice>}
              {items.length > 0 && (
                <Card title="Emails">
                  <DataTable rows={items} rowKey={(i) => String(i.id)} columns={[
                    ...(canSend ? [{ header: "", render: (i: MailItem) => i.sendable
                      ? <input type="checkbox" aria-label={`Select ${i.name}`} checked={selected.has(i.id)} onChange={() => toggle(i.id)} /> : null }] : []),
                    { header: "Recipient", render: (i) => <><strong>{i.name}</strong><br /><span className="muted small">{i.role}</span></> },
                    { header: "To", render: (i) => <span className="small">{i.to || "—"}{i.cc && <><br />CC {i.cc}</>}</span> },
                    { header: "Employees", render: (i) => what(i) },
                    { header: "Needs attention", render: (i) => (i.key === "HR" ? "" : i.attention) },
                    { header: "Status", render: (i) => <><MailBadge status={i.status} />{i.note && <div className="small muted">{i.note}</div>}</> },
                    { header: "", render: (i) => (
                      <span className="inline-actions">
                        <button className="btn btn-ghost btn-small" onClick={() => setPreview(i)}>Preview</button>
                        {isAdmin && (i.status === "SENT" || i.status === "SAVED" || i.status === "DUPLICATE") && (
                          <button className="btn btn-ghost btn-small" onClick={() => void resend(i)}>Resend</button>
                        )}
                      </span>) },
                  ]} />
                </Card>
              )}
              {preview && (
                <Card title={preview.subject} actions={<button className="btn btn-ghost btn-small" onClick={() => setPreview(null)}>Close</button>}>
                  <p className="small muted">
                    To {preview.to || "—"}{preview.cc ? ` · CC ${preview.cc}` : ""} · {STATUS_TEXT[preview.status][0]}
                    {preview.sent_at ? ` · ${formatDateTime(preview.sent_at)} by ${preview.approved_by}` : ""} ·{" "}
                    <a href={apiUrl(`/v1/mail/${preview.id}/attachment/excel`)}>Excel attachment</a>
                    {preview.key !== "HR" && <> · <a href={apiUrl(`/v1/mail/${preview.id}/attachment/dashboard`)}>Dashboard attachment</a></>}
                  </p>
                  <iframe className="email-frame" sandbox="" title="Email preview" src={apiUrl(`/v1/mail/${preview.id}/preview`)} />
                </Card>
              )}
            </>
          )}
        </>
      )}
    </>
  );
}
