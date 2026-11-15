import { useRef, useState, type DragEvent } from "react";
import { Link } from "react-router-dom";
import { ApiError, api } from "../api/client";
import type { UploadResult } from "../api/types";
import { Card, KpiCard, Notice, PageHeader } from "../components/ui";
import { HighlightList } from "./InsightsPage";
import { formatDate } from "../format";

export function UploadPage() {
  const input = useRef<HTMLInputElement>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [conflict, setConflict] = useState<string | null>(null);
  const [result, setResult] = useState<UploadResult | null>(null);
  const [drag, setDrag] = useState(false);

  async function upload(chosen: File[], replace = false) {
    setBusy(true);
    setError(null);
    setConflict(null);
    setResult(null);
    const form = new FormData();
    chosen.forEach((f) => form.append("files", f));
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

  function choose(list: FileList | null | undefined) {
    const chosen = Array.from(list ?? []).slice(0, 2);
    if (!chosen.length) return;
    setFiles(chosen);
    void upload(chosen);
    if (input.current) input.current.value = "";
  }

  function onDrop(e: DragEvent) {
    e.preventDefault();
    setDrag(false);
    choose(e.dataTransfer.files);
  }

  const s = result?.insights.scopes.ALL.summary;
  const sentCount = result?.mail.filter((m) => m.status === "SENT" || m.status === "SAVED").length ?? 0;
  const waiting = result?.mail.filter((m) => m.status === "PENDING").length ?? 0;
  const bz = result?.insights.sources?.bizom;

  return (
    <>
      <PageHeader title="Upload yesterday's attendance" subtitle="Pocket HRMS Attendance Summary and the Bizom attendance report of the same day. Drop both together, or one at a time." />
      <div className={`dropzone${drag ? " drag" : ""}${busy ? " busy" : ""}`}
        onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)} onDrop={onDrop}
        onClick={() => !busy && input.current?.click()} role="button" tabIndex={0}
        onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && input.current?.click()}>
        <input ref={input} type="file" accept=".xlsx,.csv" multiple hidden onChange={(e) => choose(e.target.files)} />
        <div className="dropzone-icon" aria-hidden="true">⬆</div>
        <strong>{busy ? "Analysing and preparing reports…" : "Drop the Pocket HRMS and/or Bizom file here, or click to choose"}</strong>
        <span className="muted">{files.length ? files.map((f) => f.name).join(" + ") : "Excel (.xlsx) or CSV, up to 25 MB each. The file type is recognised automatically."}</span>
      </div>

      {error && <Notice kind="fail">{error}</Notice>}
      {conflict && files.length > 0 && (
        <Notice kind="warn">
          {conflict}{" "}
          <button className="btn btn-primary btn-small" onClick={() => void upload(files, true)}>Replace and send again</button>
        </Notice>
      )}

      {result && s && (
        <>
          <div className="upload-slots">
            <div className={`upload-slot${result.file ? " done" : ""}`}>
              <strong>Pocket HRMS</strong><br />{result.file ?? "Not uploaded yet for this day"}
            </div>
            <div className={`upload-slot${result.bizom_file ? " done" : ""}`}>
              <strong>Bizom</strong><br />{result.bizom_file ?? "Not uploaded yet for this day"}
              {bz && <span className="muted small"><br />{bz.matched} matched · {bz.decided} decided by Bizom · {bz.added} added · {bz.skipped} skipped</span>}
            </div>
          </div>
          <Notice kind={result.auto_sent ? "ok" : "info"}>
            {formatDate(result.report_date)} processed: {result.employees} employees
            {result.insights.excluded ? ` (${result.insights.excluded} test / inactive record(s) skipped)` : ""}.{" "}
            {result.auto_sent
              ? `${sentCount} email(s) ${result.mail.some((m) => m.status === "SAVED") ? "saved to the outbox (test mode)" : "sent"}.`
              : result.send_note ?? ""}{" "}
            {waiting > 0 && <><Link to={`/mail?date=${result.report_date}`}><strong>Review and approve {waiting} email(s) →</strong></Link>{" "}</>}
            <Link to={`/insights?date=${result.report_date}`}>Open insights →</Link>
          </Notice>
          <div className="kpi-grid">
            <KpiCard label="Attendance" value={s.attendance_pct === null ? "—" : `${s.attendance_pct}%`} />
            <KpiCard label="Present" value={s.counts.PRESENT} />
            <KpiCard label="Absent" value={s.counts.ABSENT} />
            <KpiCard label="Late" value={s.late} />
            <KpiCard label="Leave" value={s.counts.LEAVE + s.counts.HALF_DAY} />
            <KpiCard label="Week off" value={s.counts.WEEK_OFF ?? 0} />
            <KpiCard label="Not tracked" value={s.counts.NOT_TRACKED} />
          </div>
          <Card title="Highlights">
            <HighlightList items={result.insights.scopes.ALL.highlights} />
          </Card>
        </>
      )}
    </>
  );
}
