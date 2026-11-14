import { useApi } from "../api/useApi";
import type { DashboardSummary } from "../api/types";
import { Badge, ErrorNotice, KpiCard, Loading, Notice, PageHeader } from "../components/ui";
import { formatDate, formatDateTime } from "../format";

export function DashboardPage() {
  const { data, error, loading } = useApi<DashboardSummary>("/v1/dashboard/summary");

  return (
    <>
      <PageHeader title="Executive Dashboard" subtitle={data ? `Today: ${formatDate(data.today_ist)} (IST)` : undefined} />
      {loading && <Loading />}
      {error && <ErrorNotice error={error} />}
      {data && (
        <>
          <div className="kpi-grid kpi-grid-4">
            <KpiCard label="Reporting date" value={formatDate(data.reporting_date)} />
            <KpiCard label="Last successful run" value={formatDateTime(data.last_successful_run)} />
            <KpiCard label="Latest run status" value={data.latest_run_status ?? "—"} />
            <KpiCard label="Uploaded datasets" value={data.uploaded_dataset_count} />
          </div>
          <p className="rules-line">
            Attendance rules <Badge>{data.rule_version}</Badge>{" "}
            <Badge kind={data.rules_approved ? "ok" : "warn"}>{data.rule_approval_status.replace(/_/g, " ")}</Badge>
          </p>
          <Notice>{data.message}</Notice>
          <div className="kpi-grid">
            {data.kpis.map((k) => (
              <KpiCard key={k.key} label={k.label} value={k.value ?? "—"} />
            ))}
          </div>
        </>
      )}
    </>
  );
}
