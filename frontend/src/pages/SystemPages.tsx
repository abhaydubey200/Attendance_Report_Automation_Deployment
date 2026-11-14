import { useApi } from "../api/useApi";
import type { HealthItem, SystemConfig } from "../api/types";
import { Badge, DataTable, ErrorNotice, Loading, PageHeader, type BadgeKind } from "../components/ui";

const KIND: Record<HealthItem["status"], BadgeKind> = { OK: "ok", WARN: "warn", FAIL: "fail" };

export function HealthPage() {
  const { data, error, loading } = useApi<HealthItem[]>("/v1/system/health");
  return (
    <>
      <PageHeader title="System Health" subtitle="Configuration, storage, database, rules and optional services" />
      {loading && <Loading />}
      {error && <ErrorNotice error={error} />}
      {data && (
        <ul className="health-list">
          {data.map((item) => (
            <li key={item.name}>
              <Badge kind={KIND[item.status]}>{item.status}</Badge>
              <strong>{item.name}</strong>
              <span className="muted">{item.detail}</span>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

export function ConfigurationPage() {
  const { data, error, loading } = useApi<SystemConfig>("/v1/system/config");
  return (
    <>
      <PageHeader title="System Configuration" subtitle="Read-only. Secrets are never displayed." />
      {loading && <Loading />}
      {error && <ErrorNotice error={error} />}
      {data && (
        <>
          <h2>Application</h2>
          <DataTable rows={data.application} rowKey={(r) => r.key}
            columns={[{ header: "Setting", render: (r) => r.key }, { header: "Value", render: (r) => r.value }]} />

          <h2>Dataset registry</h2>
          <DataTable rows={data.datasets} rowKey={(r) => r.dataset_id}
            columns={[
              { header: "Dataset", render: (r) => r.dataset_id },
              { header: "Name", render: (r) => r.dataset_name },
              { header: "Source", render: (r) => r.source_system },
              { header: "Frequency", render: (r) => r.frequency },
              { header: "Active", render: (r) => (r.active ? "Yes" : "No") },
              { header: "Schema", render: (r) => <Badge kind={r.schema_status === "DEFINED" ? "ok" : "warn"}>{r.schema_status}</Badge> },
              { header: "Columns", render: (r) => r.columns_defined },
            ]} />

          <h2>
            Attendance rules <Badge>{data.rule_version}</Badge>{" "}
            <Badge kind={data.rule_approval_status === "APPROVED" ? "ok" : "warn"}>{data.rule_approval_status}</Badge>
          </h2>
          <DataTable rows={data.rules} rowKey={(r) => r.key}
            columns={[{ header: "Rule", render: (r) => r.key }, { header: "Value", render: (r) => r.value }]} />

          <h2>Source authority</h2>
          <DataTable rows={data.source_authority} rowKey={(r) => r.domain}
            columns={[
              { header: "Domain", render: (r) => r.domain },
              { header: "Proposed", render: (r) => r.proposed_source ?? "—" },
              { header: "Approved", render: (r) => r.authoritative_source ?? <Badge kind="warn">PENDING HR</Badge> },
            ]} />
        </>
      )}
    </>
  );
}
