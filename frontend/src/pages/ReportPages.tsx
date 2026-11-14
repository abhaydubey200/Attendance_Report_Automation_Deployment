import { useMemo, useState } from "react";
import { api, apiUrl } from "../api/client";
import { useAction, useApi } from "../api/useApi";
import type { ReportRow } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { ActionMessages, Badge, Card, DataTable, ErrorNotice, Field, Loading, Notice, PageHeader, StatusBadge, Toolbar } from "../components/ui";
import { formatDate, formatDateTime } from "../format";

type Mode = "hod" | "directors" | "preview" | "history";

const TITLES: Record<Mode, [string, string]> = {
  hod: ["HOD Reports", "Department MIS for the departments you are authorised to see"],
  directors: ["Directors Reports", "Consolidated organisation-level MIS (no employee-level data)"],
  preview: ["Report Preview", "Review the latest generated reports before approval"],
  history: ["Report History", "All generated report versions"],
};

export function ReportsPage({ mode }: { mode: Mode }) {
  const list = useApi<ReportRow[]>("/v1/reports");
  const [preview, setPreview] = useState<ReportRow | null>(null);
  const [date, setDate] = useState("");
  const act = useAction();
  const { hasPermission } = useAuth();

  const rows = useMemo(() => {
    let r = list.data ?? [];
    if (mode === "hod") r = r.filter((x) => x.report_type === "HOD");
    if (mode === "directors") r = r.filter((x) => x.report_type === "DIRECTORS");
    if (mode === "preview") {
      const latest = r.reduce((m, x) => Math.max(m, x.run_id), 0);
      r = r.filter((x) => x.run_id === latest);
    }
    if (date) r = r.filter((x) => x.reporting_date === date);
    return r;
  }, [list.data, mode, date]);

  async function decide(r: ReportRow, decision: "APPROVED" | "REJECTED") {
    const res = await act.run(() => api.post(`/v1/reports/${r.report_id}/decision`, { decision }), `Report #${r.report_id} ${decision.toLowerCase()}.`);
    if (res) list.reload();
  }

  const [title, subtitle] = TITLES[mode];
  return (
    <>
      <PageHeader title={title} subtitle={subtitle} />
      <Toolbar><Field label="Reporting date"><input type="date" value={date} onChange={(e) => setDate(e.target.value)} /></Field></Toolbar>
      <ActionMessages error={act.error} message={act.message} />
      {list.loading && <Loading />}
      {list.error && <ErrorNotice error={list.error} />}
      {list.data && !rows.length && <Notice>No reports available{date ? ` for ${formatDate(date)}` : ""}.</Notice>}
      {rows.length > 0 && (
        <DataTable rows={rows} rowKey={(r) => String(r.report_id)} columns={[
          { header: "Date", render: (r) => (r.reporting_date ? formatDate(r.reporting_date) : "") },
          { header: "Report", render: (r) => <><strong>{r.report_type.replace("_", "/")}</strong>{r.department_code ? ` — ${r.department_code}` : ""}</> },
          { header: "Format", render: (r) => r.file_format },
          { header: "Version", render: (r) => `v${r.report_version}` },
          { header: "Run", render: (r) => r.run_ref },
          { header: "Figures", render: (r) => (r.provisional ? <Badge kind="warn">PROVISIONAL</Badge> : <Badge kind="ok">OFFICIAL</Badge>) },
          { header: "Status", render: (r) => <StatusBadge value={r.status} /> },
          { header: "Generated", render: (r) => formatDateTime(r.generated_at) },
          { header: "", render: (r) => (
            <div className="inline-actions">
              {r.file_format === "HTML" && <button className="btn btn-ghost btn-small" onClick={() => setPreview(r)}>Preview</button>}
              <a className="btn btn-ghost btn-small" href={apiUrl(`/v1/reports/${r.report_id}/download`)}>Download</a>
              {hasPermission("REPORT_APPROVE") && r.status === "GENERATED" && (
                <>
                  <button className="btn btn-primary btn-small" disabled={act.busy} onClick={() => void decide(r, "APPROVED")}>Approve</button>
                  <button className="btn btn-ghost btn-small" disabled={act.busy} onClick={() => void decide(r, "REJECTED")}>Reject</button>
                </>
              )}
            </div>
          ) },
        ]} />
      )}
      {preview && (
        <Card title={`Preview — ${preview.report_type}${preview.department_code ? ` ${preview.department_code}` : ""} v${preview.report_version}`}
          actions={<button className="btn btn-ghost btn-small" onClick={() => setPreview(null)}>Close</button>}>
          <iframe className="report-frame" sandbox="" title="Report preview" src={apiUrl(`/v1/reports/${preview.report_id}/download`, { inline: true })} />
        </Card>
      )}
    </>
  );
}
