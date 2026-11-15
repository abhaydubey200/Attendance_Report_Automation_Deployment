import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, apiUrl } from "../api/client";
import { useAction, useApi } from "../api/useApi";
import type { DayDetail, DayListItem, EmailResult, EmployeeRow, Highlight } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { HBars, LineChart, STATUS_COLORS, STATUS_LABELS } from "../components/charts";
import { ActionMessages, Card, DataTable, ErrorNotice, Field, KpiCard, Loading, Notice, PageHeader, StatusBadge, Toolbar } from "../components/ui";
import { formatDate } from "../format";

export function HighlightList({ items }: { items: Highlight[] }) {
  return (
    <ul className="hl-list">
      {items.map((h, i) => <li key={i} className={`hl hl-${h.kind}`}>{h.text}</li>)}
    </ul>
  );
}

const FILTERS: [string, string][] = [["ALL", "All"], ["ABSENT", "Absent"], ["LATE", "Late"], ["MISSING_PUNCH", "Missing punch"],
  ["LEFT_EARLY", "Left early"], ["LEAVE", "Leave / on duty"], ["SHORT_HOURS", "Short hours"], ["NOT_TRACKED", "Not tracked"]];

function matches(r: EmployeeRow, f: string): boolean {
  if (f === "ALL") return true;
  if (f === "LEAVE") return ["LEAVE", "HALF_DAY", "ON_DUTY"].includes(r.status);
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
  const [preview, setPreview] = useState(false);
  const day = useApi<DayDetail>(date ? `/v1/days/${date}` : null);
  const send = useAction();
  const { hasPermission } = useAuth();

  useEffect(() => setScope("ALL"), [date]);

  const ins = day.data?.insights;
  const data = ins?.scopes[scope];
  const s = data?.summary;
  const rows = useMemo(() => {
    const q = search.trim().toLowerCase();
    return (day.data?.rows ?? []).filter((r) => (scope === "ALL" || r.category === scope) && matches(r, filter)
      && (!q || r.name.toLowerCase().includes(q) || r.code.toLowerCase().includes(q)));
  }, [day.data, scope, filter, search]);
  const trend = useMemo(() => [...(days.data ?? [])].reverse().slice(-30), [days.data]);

  async function sendNow() {
    const res = await send.run(() => api.post<{ mode: string; email_results: EmailResult[] }>(`/v1/days/${date}/send`, { scopes: null }),
      (r) => r.email_results.map((e) => `${e.scope_label}: ${e.status === "SAVED" ? "saved (test mode)" : e.status.replace("_", " ").toLowerCase()}`).join(" · "));
    if (res) day.reload();
  }

  if (days.loading) return <Loading />;
  if (days.data && !days.data.length) {
    return (<><PageHeader title="Insights" /><Notice>No day uploaded yet. Start on the Upload page.</Notice></>);
  }

  return (
    <>
      <PageHeader title="Insights" subtitle={date ? `${formatDate(date)} · ${scope === "ALL" ? "All employees" : scope}` : undefined} />
      <Toolbar>
        <Field label="Day">
          <select value={date} onChange={(e) => setParams({ date: e.target.value })}>
            {days.data?.map((d) => <option key={d.report_date} value={d.report_date}>{formatDate(d.report_date)}</option>)}
          </select>
        </Field>
        <Field label="Team">
          <select value={scope} onChange={(e) => setScope(e.target.value)}>
            <option value="ALL">All employees</option>
            {ins?.categories.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </Field>
        <div className="toolbar-actions">
          <a className="btn btn-ghost btn-inline" href={apiUrl(`/v1/days/${date}/excel`, { scope })}>Excel</a>
          <a className="btn btn-ghost btn-inline" href={apiUrl(`/v1/days/${date}/dashboard`, { scope })}>HTML dashboard</a>
          <button className="btn btn-ghost btn-inline" onClick={() => setPreview(!preview)}>{preview ? "Hide" : "Preview"} email</button>
          {hasPermission("UPLOAD_AND_SEND") && (
            <button className="btn btn-primary btn-inline" disabled={send.busy} onClick={() => void sendNow()}>
              {send.busy ? "Sending…" : "Send emails"}
            </button>
          )}
        </div>
      </Toolbar>
      <ActionMessages error={send.error} message={send.message} />
      {day.error && <ErrorNotice error={day.error} />}
      {day.loading && <Loading />}
      {preview && date && (
        <Card title="Email preview">
          <iframe className="email-frame" sandbox="" title="Email preview" src={apiUrl(`/v1/days/${date}/email-preview`, { scope })} />
        </Card>
      )}
      {s && data && ins && (
        <>
          <div className="kpi-grid">
            <KpiCard label="Attendance" value={s.attendance_pct === null ? "—" : `${s.attendance_pct}%`} />
            <KpiCard label="Employees" value={s.employees} />
            <KpiCard label="Present" value={s.counts.PRESENT} />
            <KpiCard label="Absent" value={s.counts.ABSENT} />
            <KpiCard label="Late" value={s.late} />
            <KpiCard label="Missing punch" value={s.counts.MISSING_PUNCH} />
            <KpiCard label="Leave" value={s.counts.LEAVE + s.counts.HALF_DAY} />
            <KpiCard label="On duty" value={s.counts.ON_DUTY} />
            <KpiCard label="Left early" value={s.left_early} />
            <KpiCard label="Avg arrival" value={s.avg_in_time ?? "—"} />
            <KpiCard label="Avg hours" value={s.avg_work_hours ?? "—"} />
            <KpiCard label="Not tracked" value={s.counts.NOT_TRACKED} />
          </div>

          <Card title="Highlights"><HighlightList items={data.highlights} /></Card>

          <div className="grid-2">
            <Card title="Status breakdown">
              <HBars title="Employees by status" bars={(Object.keys(STATUS_LABELS) as (keyof typeof s.counts)[])
                .filter((k) => s.counts[k]).map((k) => ({ label: STATUS_LABELS[k], value: s.counts[k], color: STATUS_COLORS[k] }))} />
            </Card>
            <Card title="Arrival times">
              <HBars title="Employees arriving in each 30-minute window" bars={data.arrivals.map((a) => ({ label: a.label, value: a.count, color: "#d7ad5f" }))} />
            </Card>
            {scope === "ALL" && ins.categories.length > 1 && (
              <Card title="Attendance by team">
                <HBars title="Attendance % (tracked employees)" max={100} unit="%" bars={Object.entries(ins.by_category)
                  .filter(([, c]) => c.attendance_pct !== null)
                  .map(([name, c]) => ({ label: name, value: c.attendance_pct as number,
                    color: (c.attendance_pct as number) < 75 ? "#a52a1a" : (c.attendance_pct as number) < 90 ? "#c88a00" : "#2e7d4f" }))} />
              </Card>
            )}
            {scope === "ALL" && (
              <Card title="Attendance trend">
                <LineChart title="Attendance % per uploaded day" unit="%" labels={trend.map((t) => formatDate(t.report_date).slice(0, 6))}
                  values={trend.map((t) => t.attendance_pct)} />
              </Card>
            )}
          </div>

          {scope === "ALL" && ins.categories.length > 1 && (
            <Card title="Teams">
              <DataTable rows={Object.entries(ins.by_category)} rowKey={([n]) => n} columns={[
                { header: "Team", render: ([n]) => <strong>{n}</strong> },
                { header: "Employees", render: ([, c]) => c.employees },
                { header: "Attendance", render: ([, c]) => (c.attendance_pct === null ? "—" : `${c.attendance_pct}%`) },
                { header: "Present", render: ([, c]) => c.counts.PRESENT },
                { header: "Absent", render: ([, c]) => c.counts.ABSENT },
                { header: "Late", render: ([, c]) => c.late },
                { header: "Missing punch", render: ([, c]) => c.counts.MISSING_PUNCH },
                { header: "Avg arrival", render: ([, c]) => c.avg_in_time ?? "—" },
                { header: "Not tracked", render: ([, c]) => c.counts.NOT_TRACKED },
              ]} />
            </Card>
          )}

          <Card title="Employees">
            <div className="controls">
              <input className="search" placeholder="Search name or code…" value={search} onChange={(e) => setSearch(e.target.value)} aria-label="Search employees" />
              <div className="chips">
                {FILTERS.map(([k, l]) => <button key={k} className={`chip${filter === k ? " on" : ""}`} onClick={() => setFilter(k)}>{l}</button>)}
              </div>
              <span className="muted small">{rows.length} employees</span>
            </div>
            <DataTable rows={rows.slice(0, 1000)} rowKey={(r) => r.code} columns={[
              { header: "Code", render: (r) => r.code },
              { header: "Name", render: (r) => r.name },
              { header: "Team", render: (r) => r.category },
              { header: "Status", render: (r) => <span className="st" style={{ background: `${STATUS_COLORS[r.status]}22`, color: STATUS_COLORS[r.status] }}>{r.status_label}</span> },
              { header: "In", render: (r) => r.in_time ?? "" },
              { header: "Out", render: (r) => r.out_time ?? "" },
              { header: "Hours", render: (r) => r.work_hours ?? "" },
              { header: "Late", render: (r) => (r.late_minutes ? `${r.late_minutes} min` : "") },
              { header: "Left early", render: (r) => (r.early_minutes ? `${r.early_minutes} min` : "") },
              { header: "Leave", render: (r) => r.leave_type ?? "" },
            ]} />
          </Card>

          {day.data && day.data.emails.length > 0 && (
            <Card title="Emails for this day">
              <DataTable rows={day.data.emails} rowKey={(e) => `${e.scope}-${e.sent_at}`} columns={[
                { header: "Report", render: (e) => (e.scope === "ALL" ? "All employees" : e.scope) },
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
