import { useState } from "react";
import { Link } from "react-router-dom";
import { useApi, withQuery } from "../api/useApi";
import type { AttendanceSummary } from "../api/types";
import { LineChart, StackedBars, STATUS_COLORS } from "../components/charts";
import { Badge, Card, ErrorNotice, Field, KpiCard, Loading, Notice, PageHeader, StatusBadge, Toolbar, pct } from "../components/ui";
import { formatDate, formatDateTime } from "../format";

export function DashboardPage() {
  const [day, setDay] = useState("");
  const { data, error, loading } = useApi<AttendanceSummary>(withQuery("/v1/dashboard/summary", { date: day }));
  const k = data?.kpis;
  const c = k?.counts ?? {};

  return (
    <>
      <PageHeader title="Executive Dashboard" subtitle={data?.today_ist ? `Today: ${formatDate(data.today_ist)} (IST)` : undefined} />
      <Toolbar>
        <Field label="Reporting date">
          <input type="date" value={day || data?.run?.reporting_date || ""} onChange={(e) => setDay(e.target.value)} />
        </Field>
        {data?.rule_version && (
          <span className="rules-line">
            Attendance rules <Badge>{data.rule_version}</Badge>{" "}
            <Badge kind={data.rules_approved ? "ok" : "warn"}>{(data.rule_approval_status ?? "").replace(/_/g, " ")}</Badge>
          </span>
        )}
      </Toolbar>
      {loading && <Loading />}
      {error && <ErrorNotice error={error} />}
      {data && !data.run && <Notice>{data.message ?? "No processed attendance for this date."} <Link to="/upload">Upload datasets</Link></Notice>}
      {data?.run && k && (
        <>
          <div className="kpi-grid kpi-grid-4">
            <KpiCard label="Reporting date" value={formatDate(data.run.reporting_date)} />
            <KpiCard label="Last successful run" value={data.last_successful_run ? formatDateTime(data.last_successful_run.finished_at) : "—"} />
            <KpiCard label="Latest run status" value={<StatusBadge value={data.run.state} />} />
            <KpiCard label="Uploaded datasets" value={data.data_quality?.uploaded_datasets ?? 0} />
          </div>
          <p className="muted small">
            Run {data.run.run_ref} ·{" "}
            {data.run.rules_approved ? "official figures" : "PROVISIONAL figures (HR rules not yet approved)"}
          </p>
          <div className="kpi-grid">
            <KpiCard label="Active employees" value={k.active_employees ?? "—"} />
            <KpiCard label="Eligible employees" value={k.eligible_employees} />
            <KpiCard label="Present" value={c.PRESENT ?? 0} />
            <KpiCard label="Absent" value={c.ABSENT ?? 0} />
            <KpiCard label="Approved leave" value={c.APPROVED_LEAVE ?? 0} />
            <KpiCard label="WFH" value={c.WORK_FROM_HOME ?? 0} />
            <KpiCard label="Half day" value={c.HALF_DAY ?? 0} />
            <KpiCard label="Missing punch" value={c.MISSING_PUNCH ?? 0} />
            <KpiCard label="Pending review" value={k.pending_review} />
            <KpiCard label="Attendance %" value={<span className="kpi-small">{pct(k.attendance_pct)}</span>} />
          </div>

          <div className="grid-2">
            <Card title="Department attendance">
              <StackedBars title="Status by department" rows={(data.departments ?? []).map((d) => ({ label: d.department_code, counts: d.counts }))} />
            </Card>
            <Card title="Location attendance">
              <StackedBars title="Status by location" rows={(data.locations ?? []).map((l) => ({ label: l.location_code, counts: l.counts }))} />
            </Card>
          </div>
          <Card title="Daily trend (last 14 days)">
            <LineChart
              title="Present and absent per day"
              labels={(data.trend ?? []).map((t) => formatDate(t.date).slice(0, 6))}
              series={[
                { name: "Present", color: STATUS_COLORS.PRESENT, values: (data.trend ?? []).map((t) => t.counts.PRESENT ?? 0) },
                { name: "Absent", color: STATUS_COLORS.ABSENT, values: (data.trend ?? []).map((t) => t.counts.ABSENT ?? 0) },
                { name: "Unresolved", color: STATUS_COLORS.UNRESOLVED, values: (data.trend ?? []).map((t) => t.counts.UNRESOLVED ?? 0) },
              ]}
            />
          </Card>
          <div className="grid-2">
            <Card title="Reconciliation exceptions">
              <ul className="kv-list">
                <li><span>Open exceptions</span><strong>{data.exceptions?.open ?? 0}</strong></li>
                <li><span>Critical / high</span><strong>{data.exceptions?.critical ?? 0}</strong></li>
                {Object.entries(data.exceptions?.by_category ?? {}).map(([cat, n]) => (
                  <li key={cat}><StatusBadge value={cat} /><strong>{n}</strong></li>
                ))}
              </ul>
              <Link to="/exception-resolution">Review exceptions</Link>
            </Card>
            <Card title="Operational indicators">
              <ul className="kv-list">
                <li><span>Missing datasets</span><strong>{data.data_quality?.missing_datasets.join(", ") || "None"}</strong></li>
                <li><span>Invalid records</span><strong>{data.data_quality?.invalid_records ?? 0}</strong></li>
                {data.data_quality?.unmapped_employees !== null && (
                  <li><span>Unmapped employees</span><strong>{data.data_quality?.unmapped_employees}</strong></li>
                )}
                {data.data_quality?.conflicting_records !== null && (
                  <li><span>Conflicting records</span><strong>{data.data_quality?.conflicting_records}</strong></li>
                )}
                <li><span>Pending review</span><strong>{k.pending_review}</strong></li>
              </ul>
            </Card>
          </div>
        </>
      )}
    </>
  );
}
