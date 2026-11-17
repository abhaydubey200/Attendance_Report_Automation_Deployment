import { Link } from "react-router-dom";
import { useApi } from "../api/useApi";
import { useAuth } from "../auth/AuthContext";
import { Icon } from "../components/icons";
import { Card, ErrorNotice, Loading, PageHeader, StatusBadge } from "../components/ui";
import type { Highlight } from "../api/types";
import { HighlightList } from "./InsightsPage";
import { formatDate, formatDateTime, formatTime } from "../format";

interface JobInfo { job: string; target: string | null; status: string; started_at: string; error: string | null }
interface Overview {
  latest: null | {
    date: string; employees: number; tracked: number; attendance_pct: number | null; present: number; absent: number; late: number;
    left_early: number; missing_punch: number; leave: number; avg_in_time: string | null; permission_file: boolean; highlights: Highlight[];
  };
  previous: null | { date: string; attendance_pct: number | null; absent: number; late: number; missing_punch: number };
  trend: { date: string; attendance_pct: number | null; absent: number }[];
  emails: null | { date: string; total: number; pending: number; sent: number; failed: number; held: number; held_notes: string[] };
  jobs: Record<string, JobInfo | null>;
  issues: { kind: "warn" | "info" | "fail"; text: string; link: string }[];
  setup: { text: string; link: string }[];
  month: null | { month: string; label: string; attendance_pct: number | null; status: string };
  email_mode: string;
  employees_active: number;
  last_backup: JobInfo | null;
}

function greeting(): string {
  const h = new Date().getHours();
  return h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
}

function Ring({ value }: { value: number | null }) {
  const v = value ?? 0;
  const r = 54, c = 2 * Math.PI * r;
  const color = v >= 90 ? "var(--ok-fg)" : v >= 75 ? "var(--gold-600)" : "var(--fail-fg)";
  return (
    <div className="ring" aria-label={`Attendance ${value ?? "-"} percent`}>
      <svg viewBox="0 0 132 132" aria-hidden="true">
        <circle cx="66" cy="66" r={r} fill="none" stroke="var(--line)" strokeWidth="12" />
        <circle cx="66" cy="66" r={r} fill="none" stroke={color} strokeWidth="12" strokeLinecap="round"
          strokeDasharray={`${(c * Math.min(v, 100)) / 100} ${c}`} />
      </svg>
      <div className="ring-c">
        <span className="ring-v">{value === null ? "–" : `${value}%`}</span>
        <span className="ring-l">attendance</span>
      </div>
    </div>
  );
}

/** Change vs the previous day; `goodUp` says whether a rise is good news. */
function Delta({ now, before, goodUp, unit = "" }: { now: number | null | undefined; before: number | null | undefined; goodUp: boolean; unit?: string }) {
  if (now === null || now === undefined || before === null || before === undefined) return null;
  const d = Math.round((now - before) * 10) / 10;
  if (d === 0) return <span className="delta flat">same as previous day</span>;
  const good = d > 0 === goodUp;
  return <span className={`delta ${good ? "up" : "down"}`}>{d > 0 ? "▲" : "▼"} {Math.abs(d)}{unit} vs previous day</span>;
}

function Spark({ points }: { points: { date: string; attendance_pct: number | null }[] }) {
  const vals = points.map((p) => p.attendance_pct ?? 0);
  if (vals.length < 2) return <p className="muted small">The trend appears after two uploaded days.</p>;
  const w = 320, h = 80, pad = 6;
  const min = Math.min(...vals, 60), max = 100;
  const x = (i: number) => pad + (i * (w - 2 * pad)) / (vals.length - 1);
  const y = (v: number) => h - pad - ((v - min) / (max - min || 1)) * (h - 2 * pad);
  const line = vals.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  return (
    <svg className="spark" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" role="img" aria-label="Attendance trend">
      <path d={`${line} L${x(vals.length - 1)},${h} L${x(0)},${h} Z`} fill="rgba(245,184,0,.14)" />
      <path d={line} fill="none" stroke="var(--navy)" strokeWidth="2" vectorEffect="non-scaling-stroke" />
      {vals.map((v, i) => (
        <circle key={points[i].date} cx={x(i)} cy={y(v)} r="2.6" fill={i === vals.length - 1 ? "var(--gold-600)" : "var(--navy)"}>
          <title>{`${formatDate(points[i].date)}: ${v}%`}</title>
        </circle>
      ))}
    </svg>
  );
}

const JOB_LABEL: Record<string, string> = { daily: "Daily emails", backup: "Database backup", monthly: "Month-end report" };

export function HomePage() {
  const { me } = useAuth();
  const o = useApi<Overview>("/v1/overview");
  const can = (slug: string) => !!me?.navigation.some((p) => p.slug === slug);
  const name = me?.display_name || me?.username || "";

  if (o.loading && !o.data) return (<><PageHeader title={`${greeting()}`} /><Loading lines={5} /></>);
  if (o.error) return (<><PageHeader title="Home" /><ErrorNotice error={o.error} /></>);
  const d = o.data!;
  const l = d.latest, p = d.previous, e = d.emails;

  const tasks: { kind: string; text: string; link: string }[] = [];
  if (!l) tasks.push({ kind: "info", text: "Upload the first Attendance Summary to get started", link: "/upload" });
  if (e && e.pending > 0) tasks.push({ kind: "warn", text: `${e.pending} email(s) for ${formatDate(e.date)} are waiting for your approval`, link: "/mail" });
  if (e && e.failed > 0) tasks.push({ kind: "fail", text: `${e.failed} email(s) for ${formatDate(e.date)} failed to send`, link: "/mail" });
  if (e && e.held > 0) tasks.push({ kind: "warn", text: `${e.held} email(s) are held${e.held_notes.length ? `: ${e.held_notes.join(" ")}` : ""}`, link: "/mail" });
  d.issues.forEach((i) => tasks.push(i));
  d.setup.forEach((s) => tasks.push({ kind: "info", text: s.text, link: s.link }));
  if (e && e.total > 0 && e.pending === 0 && e.failed === 0) tasks.push({ kind: "ok", text: `All emails for ${formatDate(e.date)} are sent (${e.sent})`, link: "/emails" });

  return (
    <>
      <PageHeader
        title={`${greeting()}${name ? `, ${name}` : ""}`}
        subtitle={l ? `Latest attendance: ${formatDate(l.date)} · ${d.employees_active} active employees` : "No attendance uploaded yet"}
        actions={can("upload") ? <Link className="btn btn-primary btn-inline" to="/upload"><Icon name="upload" className="btn-icon" /> Upload a day</Link> : undefined}
      />
      <div className="home-grid">
        <div>
          {l && (
            <Card title={`Attendance on ${formatDate(l.date)}`} actions={<Link className="btn btn-ghost btn-small" to={`/insights?date=${l.date}`}>Open full insights ›</Link>}>
              <div className="hero">
                <Ring value={l.attendance_pct} />
                <div>
                  <Delta now={l.attendance_pct} before={p?.attendance_pct} goodUp unit=" pts" />
                  <div className="mini-stats">
                    <Link className="mini" to={`/insights?date=${l.date}`}><b>{l.present}</b><span>Present of {l.tracked}</span></Link>
                    <Link className={`mini${l.absent ? " bad" : ""}`} to={`/insights?date=${l.date}`}><b>{l.absent}</b><span>Absent</span></Link>
                    <Link className={`mini${l.late ? " warn" : ""}`} to={`/insights?date=${l.date}`}><b>{l.late}</b><span>Late arrivals</span></Link>
                    <Link className={`mini${l.missing_punch ? " warn" : ""}`} to={`/insights?date=${l.date}`}><b>{l.missing_punch}</b><span>Missing punch</span></Link>
                    <div className="mini"><b>{l.leave}</b><span>On leave</span></div>
                    <div className="mini"><b>{l.left_early}</b><span>Left early</span></div>
                    <div className="mini"><b>{l.avg_in_time ? formatTime(l.avg_in_time) : "–"}</b><span>Average in-time</span></div>
                    <div className="mini"><b>{l.permission_file ? "Yes" : "No"}</b><span>Permission file</span></div>
                  </div>
                  {p && <p className="muted small" style={{ marginTop: ".6rem" }}>Previous day {formatDate(p.date)}: {p.attendance_pct ?? "–"}% · {p.absent} absent · {p.late} late</p>}
                </div>
              </div>
              {l.highlights.length > 0 && <div style={{ marginTop: "1rem" }}><HighlightList items={l.highlights} /></div>}
            </Card>
          )}
          <Card title="Needs your attention">
            {tasks.length === 0 ? <p className="muted">Nothing needs you right now.</p> : (
              <ul className="task-list">
                {tasks.map((t) => (
                  <li key={t.text}>
                    <Link className={`task ${t.kind}`} to={t.link}><span className="tdot" /><span>{t.text}</span><span className="tgo">›</span></Link>
                  </li>
                ))}
              </ul>
            )}
          </Card>
          <Card title={`Attendance trend (last ${d.trend.length} uploaded days)`}>
            <Spark points={d.trend} />
          </Card>
        </div>
        <div>
          <Card title="Quick actions">
            <div className="quick">
              {can("upload") && <Link to="/upload"><Icon name="upload" /> Upload a day</Link>}
              {can("mail") && <Link to="/mail"><Icon name="mail" /> Approve emails</Link>}
              {can("insights") && <Link to="/insights"><Icon name="insights" /> Insights</Link>}
              {can("reports") && <Link to="/reports"><Icon name="reports" /> Reports</Link>}
              {can("employees") && <Link to="/employees"><Icon name="employees" /> Employees</Link>}
              {can("emails") && <Link to="/emails"><Icon name="emails" /> Email log</Link>}
            </div>
          </Card>
          {e && (
            <Card title={`Emails for ${formatDate(e.date)}`}>
              <div className="mini-stats" style={{ gridTemplateColumns: "repeat(2, minmax(0, 1fr))", marginTop: 0 }}>
                <div className="mini"><b>{e.sent}</b><span>Sent</span></div>
                <div className={`mini${e.pending ? " warn" : ""}`}><b>{e.pending}</b><span>Waiting approval</span></div>
                <div className={`mini${e.failed ? " bad" : ""}`}><b>{e.failed}</b><span>Failed</span></div>
                <div className="mini"><b>{e.held}</b><span>Held</span></div>
              </div>
              <p className="muted small" style={{ marginTop: ".6rem" }}>Email mode: <b>{d.email_mode === "live" ? "Live (delivered)" : "Test (saved only)"}</b></p>
            </Card>
          )}
          <Card title="Automatic jobs">
            {(["daily", "backup", "monthly"] as const).map((k) => {
              const j = d.jobs[k];
              return (
                <div className="job-row" key={k}>
                  <span>{JOB_LABEL[k]}</span>
                  {j ? <StatusBadge value={j.status} /> : <span className="muted small">never run</span>}
                  <span className="when">{j ? formatDateTime(j.started_at) : ""}</span>
                </div>
              );
            })}
            {d.month && <p className="muted small" style={{ marginTop: ".6rem" }}>Last month-end report: {d.month.label} ({d.month.attendance_pct ?? "–"}%)</p>}
          </Card>
        </div>
      </div>
    </>
  );
}
