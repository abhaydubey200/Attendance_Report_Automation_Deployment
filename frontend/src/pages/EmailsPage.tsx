import { Link } from "react-router-dom";
import { useApi } from "../api/useApi";
import type { EmailLogRow } from "../api/types";
import { DataTable, ErrorNotice, Loading, Notice, PageHeader, StatusBadge } from "../components/ui";
import { formatDate, formatDateTime } from "../format";

export function EmailsPage() {
  const log = useApi<EmailLogRow[]>("/v1/emails");
  return (
    <>
      <PageHeader title="Emails" subtitle="Every report email: who it went to and whether it was delivered" />
      {log.loading && <Loading />}
      {log.error && <ErrorNotice error={log.error} />}
      {log.data && !log.data.length && <Notice>No emails yet. They are sent automatically after each upload.</Notice>}
      {log.data && log.data.some((e) => e.mode === "TEST") && (
        <Notice kind="warn">Test mode: emails are saved in the outbox folder, not delivered. Switch to live in <Link to="/settings">Settings</Link>.</Notice>
      )}
      {log.data && log.data.length > 0 && (
        <DataTable rows={log.data} rowKey={(e) => String(e.id)} columns={[
          { header: "Day", render: (e) => <Link to={`/insights?date=${e.report_date}`}>{formatDate(e.report_date)}</Link> },
          { header: "Report", render: (e) => (e.scope === "ALL" ? "All employees" : e.scope) },
          { header: "To", render: (e) => e.recipients },
          { header: "Subject", render: (e) => <span className="small">{e.subject}</span> },
          { header: "Status", render: (e) => <StatusBadge value={e.status} /> },
          { header: "Mode", render: (e) => e.mode },
          { header: "When", render: (e) => formatDateTime(e.sent_at) },
          { header: "Note", render: (e) => <span className="small">{e.error ?? ""}</span> },
        ]} />
      )}
    </>
  );
}
