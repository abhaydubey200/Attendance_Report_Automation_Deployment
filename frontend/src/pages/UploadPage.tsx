import { useEffect, useRef, useState, type DragEvent } from "react";
import { Link } from "react-router-dom";
import { ApiError, api } from "../api/client";
import { useApi } from "../api/useApi";
import type { UploadOptions, UploadResult } from "../api/types";
import { Card, KpiCard, Notice, PageHeader } from "../components/ui";
import { Icon } from "../components/icons";
import { HighlightList } from "./InsightsPage";
import { formatDate } from "../format";

type Slot = "master" | "hrms" | "permission";
type Mode = "auto" | "manual";

const SLOTS: { key: Slot; step: string; title: string; hint: string }[] = [
  { key: "master", step: "1", title: "Employee master", hint: "Optional – only when it changed. Routing workbook or Employee Amendment Excel." },
  { key: "hrms", step: "2", title: "Attendance Summary", hint: "Pocket HRMS → AttendanceSummary (.xlsx) for the day." },
  { key: "permission", step: "3", title: "Permission Report", hint: "Pocket HRMS → PermissionReportAdmin (.xlsx): short-leave permissions." },
];

function FileSlot({ slot, file, disabled, onPick, onClear }: {
  slot: (typeof SLOTS)[number]; file: File | null; disabled: boolean; onPick: (f: File) => void; onClear: () => void;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [drag, setDrag] = useState(false);
  const drop = (e: DragEvent) => {
    e.preventDefault();
    setDrag(false);
    const f = e.dataTransfer.files?.[0];
    if (f && !disabled) onPick(f);
  };
  return (
    <div className={`upload-box${file ? " chosen" : ""}${drag ? " drag" : ""}${disabled ? " off" : ""}`}
      onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)} onDrop={drop}>
      <div className="upload-box-head"><span className="step">{slot.step}</span> <strong>{slot.title}</strong></div>
      <p className="muted small">{slot.hint}</p>
      <input ref={input} type="file" accept=".xlsx,.csv" hidden aria-label={`${slot.title} file`}
        onChange={(e) => { const f = e.target.files?.[0]; if (f) onPick(f); e.target.value = ""; }} />
      {file ? (
        <div className="upload-file"><span title={file.name}>{file.name}</span>
          <button className="btn btn-ghost btn-small" onClick={onClear} disabled={disabled}>Remove</button></div>
      ) : (
        <button className="btn btn-ghost btn-small" disabled={disabled} onClick={() => input.current?.click()}>
          {disabled ? "Not allowed" : "Choose or drop file"}
        </button>
      )}
    </div>
  );
}

export function UploadPage() {
  const options = useApi<UploadOptions>("/v1/upload/options");
  const [chosen, setChosen] = useState<Record<Slot, File | null>>({ master: null, hrms: null, permission: null });
  const [mode, setMode] = useState<Mode>("manual");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [conflict, setConflict] = useState<string | null>(null);
  const [result, setResult] = useState<UploadResult | null>(null);

  useEffect(() => { if (options.data) setMode(options.data.default_mode); }, [options.data]);

  const any = chosen.master || chosen.hrms || chosen.permission;
  const set = (slot: Slot, f: File | null) => { setChosen({ ...chosen, [slot]: f }); setResult(null); setConflict(null); setError(null); };

  async function upload(replace = false) {
    setBusy(true);
    setError(null);
    setConflict(null);
    setResult(null);
    const form = new FormData();
    (Object.keys(chosen) as Slot[]).forEach((k) => { const f = chosen[k]; if (f) form.append(k, f); });
    form.append("replace", replace ? "true" : "false");
    form.append("send_mode", mode);
    try {
      const r = await api.upload<UploadResult>("/v1/days/upload", form);
      setResult(r);
      setChosen({ master: null, hrms: null, permission: null });
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) setConflict(e.message);
      else setError(e instanceof ApiError ? e.message : "Unable to reach the server.");
    } finally {
      setBusy(false);
    }
  }

  const s = result?.report_date ? result.insights.scopes.ALL.summary : null;
  const sentCount = result?.mail.filter((m) => m.status === "SENT" || m.status === "SAVED").length ?? 0;
  const waiting = result?.mail.filter((m) => m.status === "PENDING").length ?? 0;
  const pm = result?.insights?.sources?.permissions;
  const mi = result?.master_import;
  const test = options.data?.mode === "test";
  const stage = busy ? 2 : result?.report_date ? 3 : 1;
  const steps = ["Choose files", "Check and process", "Review and send"];

  return (
    <>
      <PageHeader title="Upload yesterday's attendance" subtitle="Up to three datasets at once. The file type is checked; columns and date are validated before anything is sent." />

      <ol className="stepper" aria-label="Upload progress">
        {steps.map((t, i) => (
          <li key={t} style={{ display: "contents" }}>
            {i > 0 && <span className="stp-line" aria-hidden="true" />}
            <span className={`stp${stage === i + 1 ? " on" : stage > i + 1 ? " done" : ""}`} aria-current={stage === i + 1 ? "step" : undefined}>
              <b>{stage > i + 1 ? "✓" : i + 1}</b>{t}
            </span>
          </li>
        ))}
      </ol>

      {options.data?.test_recipient && (
        <Notice kind="fail"><strong>Testing:</strong> all emails go only to <strong>{options.data.test_recipient}</strong>{options.data.test_cc?.length ? ` (CC ${options.data.test_cc.join(", ")})` : ""} (Settings → Testing).</Notice>
      )}
      <div className="upload-grid">
        {SLOTS.map((slot) => (
          <FileSlot key={slot.key} slot={slot} file={chosen[slot.key]} onPick={(f) => set(slot.key, f)} onClear={() => set(slot.key, null)}
            disabled={busy || (slot.key === "master" && options.data?.can_import_master === false)} />
        ))}
      </div>

      <Card title="Email sending for this upload">
        <div className="mode-choice" role="radiogroup" aria-label="Email sending">
          <label className={`mode-option${mode === "manual" ? " on" : ""}`}>
            <input type="radio" name="mode" value="manual" checked={mode === "manual"} onChange={() => setMode("manual")} />
            <span><strong>Manual</strong> – prepare the emails; I check them on “Approve emails” and send.</span>
          </label>
          <label className={`mode-option${mode === "auto" ? " on" : ""}`}>
            <input type="radio" name="mode" value="auto" checked={mode === "auto"} onChange={() => setMode("auto")} />
            <span><strong>Auto</strong> – send every email automatically as soon as the files are processed.</span>
          </label>
        </div>
        <p className="muted small">
          Default from Settings: {options.data?.default_mode === "auto" ? "Auto" : "Manual"}.
          {options.data?.wait_for_permission && " Emails are prepared once both the Attendance Summary and the Permission Report of the day are in."}
          {test && " Email is in test mode: “sent” emails are saved to the outbox, not delivered."}
          {" "}Each person still gets at most one email per day.
        </p>
        <div className="form-actions">
          <button className="btn btn-primary btn-inline" disabled={busy || !any} onClick={() => void upload()}>
            {busy ? "Processing…" : mode === "auto" && (chosen.hrms || chosen.permission) ? "Upload and send emails" : "Upload"}
          </button>
          {!any && <span className="muted small">Choose at least one file.</span>}
        </div>
        {busy && <><div className="progress" aria-hidden="true"><i /></div><p className="muted small" role="status">Reading the files, checking columns and dates, classifying attendance and preparing the emails…</p></>}
      </Card>

      {error && <Notice kind="fail">{error}</Notice>}
      {conflict && (
        <Notice kind="warn">
          {conflict}{" "}
          <button className="btn btn-primary btn-small" onClick={() => void upload(true)}>Replace with these files</button>
        </Notice>
      )}

      {mi && (
        <Notice kind={mi.problem_count ? "warn" : "ok"}>
          Employee master: {mi.rows} rows · {mi.added} added · {mi.updated} updated · {mi.unchanged} unchanged
          {mi.routing?.coverage && ` · routing check: ${mi.routing.coverage.differences === 0 ? "matches the coverage sheet ✓" : `${mi.routing.coverage.differences} difference(s)`}`}
          {mi.routing?.config && mi.routing.config.disabled.length > 0 && ` · ${mi.routing.config.disabled.length} report type(s) switched off by the workbook (Settings)`}
          . <Link to="/employees">Open Employees →</Link>
        </Notice>
      )}
      {result && !result.report_date && result.send_note && <Notice>{result.send_note}</Notice>}

      {result && s && result.report_date && (
        <>
          <div className="upload-slots">
            <div className={`upload-slot${result.file ? " done" : ""}`}>
              <strong>Attendance Summary</strong><br />{result.file ?? "Not uploaded yet for this day"}
            </div>
            <div className={`upload-slot${result.permission_file ? " done" : ""}`}>
              <strong>Permission Report</strong><br />{result.permission_file ?? "Not uploaded yet for this day"}
              {pm && <span className="muted small"><br />{pm.today} for this day · {pm.approved} approved · {pm.pending} pending
                {pm.excused_late + pm.excused_early > 0 && ` · excused ${pm.excused_late} late / ${pm.excused_early} early`}</span>}
            </div>
          </div>
          <Notice kind={result.auto_sent ? "ok" : "info"}>
            {formatDate(result.report_date)} processed: {result.employees} employees
            {result.insights.excluded ? ` (${result.insights.excluded} test / inactive record(s) skipped)` : ""}.{" "}
            {result.auto_sent
              ? `Auto: ${sentCount} email(s) ${result.mail.some((m) => m.status === "SAVED") ? "saved to the outbox (test mode)" : "sent"}.`
              : result.send_note ?? ""}{" "}
            {waiting > 0 && <><Link to={`/mail?date=${result.report_date}`}><strong>Review and approve {waiting} email(s) →</strong></Link>{" "}</>}
            {result.auto_sent && <><Link to={`/mail?date=${result.report_date}`}>See the emails →</Link>{" "}</>}
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
          <Card title="Next steps">
            <div className="next-steps">
              {waiting > 0 && <Link className="btn btn-primary btn-inline" to={`/mail?date=${result.report_date}`}><Icon name="mail" className="btn-icon" /> Review and approve {waiting} email(s)</Link>}
              {result.auto_sent && <Link className="btn btn-primary btn-inline" to={`/mail?date=${result.report_date}`}><Icon name="mail" className="btn-icon" /> See the emails</Link>}
              <Link className="btn btn-ghost btn-inline" to={`/insights?date=${result.report_date}`}><Icon name="insights" className="btn-icon" /> Open insights</Link>
              {!result.permission_file && <span className="muted small" style={{ alignSelf: "center" }}>The Permission Report of this day can still be uploaded here.</span>}
            </div>
          </Card>
        </>
      )}
    </>
  );
}
