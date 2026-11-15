import { useRef, useState, type DragEvent } from "react";
import { Link } from "react-router-dom";
import { ApiError, api } from "../api/client";
import type { UploadResult } from "../api/types";
import { Card, DataTable, KpiCard, Notice, PageHeader, StatusBadge } from "../components/ui";
import { HighlightList } from "./InsightsPage";
import { formatDate } from "../format";

export function UploadPage() {
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [conflict, setConflict] = useState<string | null>(null);
  const [result, setResult] = useState<UploadResult | null>(null);
  const [drag, setDrag] = useState(false);

  async function upload(f: File, replace = false) {
    setBusy(true);
    setError(null);
    setConflict(null);
    setResult(null);
    const form = new FormData();
    form.append("file", f);
    form.append("replace", replace ? "true" : "false");
    try {
      setResult(await api.upload<UploadResult>("/v1/days/upload", form));
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) setConflict(e.message);
      else setError(e instanceof ApiError ? e.message : "Unable to reach the server.");
    } finally {
      setBusy(false);
    }
  }

  function choose(f: File | undefined) {
    if (!f) return;
    setFile(f);
    void upload(f);
  }

  function onDrop(e: DragEvent) {
    e.preventDefault();
    setDrag(false);
    choose(e.dataTransfer.files?.[0]);
  }

  const s = result?.insights.scopes.ALL.summary;
  const sentCount = result?.email_results.filter((r) => r.status === "SENT" || r.status === "SAVED").length ?? 0;

  return (
    <>
      <PageHeader title="Upload today's attendance" subtitle="Pocket HRMS → Attendance Summary export (.xlsx). One day per file." />
      <div className={`dropzone${drag ? " drag" : ""}${busy ? " busy" : ""}`}
        onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)} onDrop={onDrop}
        onClick={() => !busy && input.current?.click()} role="button" tabIndex={0}
        onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && input.current?.click()}>
        <input ref={input} type="file" accept=".xlsx,.csv" hidden onChange={(e) => choose(e.target.files?.[0])} />
        <div className="dropzone-icon" aria-hidden="true">⬆</div>
        <strong>{busy ? "Analysing and preparing reports…" : "Drop the Attendance Summary file here, or click to choose"}</strong>
        <span className="muted">{file ? file.name : "Excel (.xlsx) or CSV, up to 25 MB"}</span>
      </div>

      {error && <Notice kind="fail">{error}</Notice>}
      {conflict && file && (
        <Notice kind="warn">
          {conflict}{" "}
          <button className="btn btn-primary btn-small" onClick={() => void upload(file, true)}>Replace and send again</button>
        </Notice>
      )}

      {result && s && (
        <>
          <Notice kind="ok">
            {formatDate(result.report_date)} processed: {result.employees} employees
            {result.insights.excluded ? ` (${result.insights.excluded} test record(s) skipped)` : ""}.{" "}
            {result.auto_sent ? `${sentCount} email(s) ${result.email_results.some((r) => r.status === "SAVED") ? "prepared (test mode)" : "sent"}.` : "Auto-send is off."}{" "}
            <Link to={`/insights?date=${result.report_date}`}>Open insights →</Link>
          </Notice>
          <div className="kpi-grid">
            <KpiCard label="Attendance" value={s.attendance_pct === null ? "—" : `${s.attendance_pct}%`} />
            <KpiCard label="Present" value={s.counts.PRESENT} />
            <KpiCard label="Absent" value={s.counts.ABSENT} />
            <KpiCard label="Late" value={s.late} />
            <KpiCard label="Leave" value={s.counts.LEAVE + s.counts.HALF_DAY} />
            <KpiCard label="Not tracked" value={s.counts.NOT_TRACKED} />
          </div>
          <Card title="Highlights">
            <HighlightList items={result.insights.scopes.ALL.highlights} />
          </Card>
          <Card title="Emails">
            <DataTable rows={result.email_results} rowKey={(r) => r.scope} columns={[
              { header: "Report", render: (r) => r.scope_label },
              { header: "To", render: (r) => r.recipients.join(", ") || "—" },
              { header: "Status", render: (r) => <StatusBadge value={r.status} /> },
              { header: "Note", render: (r) => (r.status === "SAVED" ? "Test mode: saved, not sent" : r.detail ?? "") },
            ]} />
            {result.email_results.some((r) => r.status === "NO_RECIPIENTS") && (
              <p className="muted small">Add managers in <Link to="/settings">Settings</Link>, then use “Send emails” on the Insights page.</p>
            )}
          </Card>
        </>
      )}
    </>
  );
}
