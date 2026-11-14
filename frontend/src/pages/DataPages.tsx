import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { api, apiUrl } from "../api/client";
import { istIso, shiftIso, useDefaultDate } from "../api/dates";
import { useAction, useApi, withQuery } from "../api/useApi";
import type { DatasetInfo, FieldCatalog, InspectResult, SchemaDef, UploadInfo } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import {
  ActionMessages, Card, DataTable, ErrorNotice, Field, KpiCard, Loading, Notice, PageHeader, StatusBadge, Toolbar,
} from "../components/ui";
import { formatDate, formatDateTime } from "../format";

function IssuesTable({ issues }: { issues: { row_number: number | null; column_name: string | null; code: string; severity: string; message: string }[] }) {
  return (
    <DataTable rows={issues} rowKey={(i) => `${i.row_number}-${i.code}-${i.column_name}-${i.message}`} columns={[
      { header: "Row", render: (i) => i.row_number ?? "file" },
      { header: "Column", render: (i) => i.column_name ?? "" },
      { header: "Severity", render: (i) => <StatusBadge value={i.severity === "ERROR" ? "FAIL" : "WARN"} /> },
      { header: "Code", render: (i) => i.code },
      { header: "Message", render: (i) => i.message },
    ]} />
  );
}

// ------------------------------------------------------------------ Upload Datasets
export function UploadPage() {
  const datasets = useApi<DatasetInfo[]>("/v1/datasets");
  const [day, setDay] = useDefaultDate();
  const [datasetId, setDatasetId] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [sheet, setSheet] = useState("");
  const [headerRow, setHeaderRow] = useState(1);
  const [result, setResult] = useState<InspectResult | null>(null);
  const [ack, setAck] = useState(false);
  const [supersede, setSupersede] = useState(false);
  const [reprocess, setReprocess] = useState(false);
  const inspectAction = useAction();
  const confirmAction = useAction();
  const { hasPermission } = useAuth();
  const ds = datasets.data?.find((d) => d.dataset_id === datasetId);

  useEffect(() => {
    if (!datasetId && datasets.data?.length) setDatasetId(datasets.data[0].dataset_id);
  }, [datasets.data, datasetId]);

  async function inspect(e?: FormEvent) {
    e?.preventDefault();
    if (!file || !ds) return;
    const form = new FormData();
    form.append("file", file);
    form.append("dataset_id", ds.dataset_id);
    form.append("source_system", ds.source_system);
    form.append("reporting_date", day);
    form.append("header_row", String(headerRow));
    if (sheet) form.append("sheet", sheet);
    setResult(null);
    setAck(false);
    setSupersede(false);
    setReprocess(false);
    confirmAction.setMessage(null);
    const r = await inspectAction.run(() => api.upload<InspectResult>("/v1/uploads/inspect", form));
    if (r) setResult(r);
  }

  async function confirm() {
    if (!result?.token) return;
    const up = await confirmAction.run(
      () => api.post<UploadInfo>(`/v1/uploads/${result.token}/confirm`, { acknowledge_review: ack, supersede, reprocess }),
      (u) => `Upload #${u.upload_id} accepted: ${u.valid_rows} valid rows standardized, status ${u.status.replace(/_/g, " ")}.`,
    );
    if (up) setResult(null);
  }

  const v = result?.validation;
  const needsAck = v?.status === "REQUIRES_REVIEW";
  const canSubmit = result?.can_confirm && (!needsAck || ack) && (!result.current_upload || supersede || reprocess)
    && (!result.duplicate_of || reprocess);

  return (
    <>
      <PageHeader title="Upload Datasets" subtitle="Inspect, validate and preview a file before it enters processing" />
      {datasets.error && <ErrorNotice error={datasets.error} />}
      <Card>
        <form className="form-grid" onSubmit={inspect}>
          <Field label="Reporting date"><input type="date" value={day} max={istIso()} onChange={(e) => setDay(e.target.value)} required /></Field>
          <Field label="Dataset">
            <select value={datasetId} onChange={(e) => { setDatasetId(e.target.value); setResult(null); }}>
              {datasets.data?.filter((d) => d.active).map((d) => <option key={d.dataset_id} value={d.dataset_id}>{d.dataset_name}</option>)}
            </select>
          </Field>
          <Field label="Source"><input value={ds?.source_system.replace("_", " ") ?? ""} readOnly /></Field>
          <Field label="File (CSV or XLSX)">
            <input type="file" accept=".csv,.xlsx" onChange={(e) => { setFile(e.target.files?.[0] ?? null); setSheet(""); setResult(null); }} required />
          </Field>
          {result?.sheets && result.sheets.length > 1 && (
            <Field label="Sheet">
              <select value={sheet || result.sheet || ""} onChange={(e) => setSheet(e.target.value)}>
                {result.sheets.map((s) => <option key={s}>{s}</option>)}
              </select>
            </Field>
          )}
          <Field label="Header row" hint={datasetId === "HRMS_ATTENDANCE_SUMMARY" ? "Found automatically for this report" : "Only if the header is not on row 1"}>
            <input type="number" min={1} max={50} value={headerRow} onChange={(e) => setHeaderRow(Number(e.target.value) || 1)} />
          </Field>
          <div className="form-actions">
            <button className="btn btn-primary" disabled={!file || inspectAction.busy}>{inspectAction.busy ? "Inspecting…" : "Preview & validate"}</button>
          </div>
        </form>
        {ds && ds.schema_status !== "DEFINED" && (
          <Notice kind="warn">
            {ds.dataset_name} has no approved column schema yet. You can preview a sample file here, then define its columns in the{" "}
            <Link to="/dataset-registry">Dataset Registry</Link>. Uploads can be accepted only after that.
          </Notice>
        )}
        <ActionMessages error={inspectAction.error} message={null} />
      </Card>

      <ActionMessages error={confirmAction.error} message={confirmAction.message} />

      {result && !result.accepted && <Notice kind="fail">{result.errors?.join(" ")}</Notice>}
      {result?.accepted && (
        <>
          <Card title="Validation results" actions={result.token ? <a className="btn btn-ghost" href={apiUrl(`/v1/uploads/pending/${result.token}/exceptions.csv`)}>Download exceptions</a> : undefined}>
            {v ? (
              <>
                <div className="kpi-grid">
                  <KpiCard label="Total records" value={v.total_rows} />
                  <KpiCard label="Valid" value={v.valid_rows} />
                  <KpiCard label="Invalid" value={v.invalid_rows} />
                  <KpiCard label="Duplicates" value={v.duplicate_rows} />
                  <KpiCard label="Warnings" value={v.warning_count} />
                  <KpiCard label="Status" value={<StatusBadge value={v.status} />} />
                </div>
                {v.issues.length > 0 && <IssuesTable issues={v.issues} />}
              </>
            ) : (
              <Notice>No schema to validate against yet ({result.row_count} rows, {result.columns?.length} columns read).</Notice>
            )}
            {result.duplicate_of && (
              <Notice kind="warn">
                This exact file was already uploaded as #{result.duplicate_of.upload_id} on {formatDateTime(result.duplicate_of.uploaded_at)}.
                {hasPermission("DATA_REGISTRY_MANAGE")
                  ? <label className="check"><input type="checkbox" checked={reprocess} onChange={(e) => setReprocess(e.target.checked)} /> Reprocess it deliberately (controlled reprocessing)</label>
                  : " Only a data administrator can reprocess it."}
              </Notice>
            )}
            {result.current_upload && !result.duplicate_of && (
              <Notice kind="warn">
                Upload #{result.current_upload.upload_id} ({result.current_upload.original_filename}) is current for this dataset and date.
                <label className="check"><input type="checkbox" checked={supersede} onChange={(e) => setSupersede(e.target.checked)} /> This corrected file supersedes it (a new processing version will be needed)</label>
              </Notice>
            )}
            {needsAck && (
              <label className="check"><input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} /> I reviewed the issues; accept the valid rows only</label>
            )}
            {result.can_confirm && (
              <div className="form-actions">
                <button className="btn btn-primary" disabled={!canSubmit || confirmAction.busy} onClick={() => void confirm()}>
                  {confirmAction.busy ? "Saving…" : "Confirm upload"}
                </button>
              </div>
            )}
          </Card>
          <Card title={`Preview (first ${result.preview?.length ?? 0} of ${result.row_count} rows)`}>
            <DataTable rows={result.preview ?? []} rowKey={(r) => JSON.stringify(r)}
              columns={(result.columns ?? []).map((col) => ({ header: col, render: (r: Record<string, string>) => r[col] }))} />
          </Card>
        </>
      )}
    </>
  );
}

// ------------------------------------------------------------------ Dataset Registry (+ schema discovery)
function parseMap(text: string, allowed: string[]): Record<string, string> {
  const out: Record<string, string> = {};
  for (const line of text.split("\n")) {
    const idx = line.lastIndexOf("=");
    if (idx < 0) continue;
    const k = line.slice(0, idx).trim();
    const v = line.slice(idx + 1).trim().toUpperCase();
    if (k && v && allowed.includes(v)) out[k] = v;
  }
  return out;
}

function SchemaEditor({ ds, catalog, onSaved }: { ds: DatasetInfo; catalog: FieldCatalog; onSaved: () => void }) {
  const fields = catalog.kinds[catalog.dataset_kind[ds.dataset_id]] ?? [];
  const existing = ds.schema;
  const [columns, setColumns] = useState<string[]>(existing ? Object.keys(existing.columns) : []);
  const [samples, setSamples] = useState<Record<string, string[]>>({});
  const [mapping, setMapping] = useState<Record<string, string>>(existing?.columns ?? {});
  const [pk, setPk] = useState<string[]>(existing?.primary_key ?? []);
  const [dateFormats, setDateFormats] = useState((existing?.date_formats ?? ["%Y-%m-%d"]).join(", "));
  const [dtFormats, setDtFormats] = useState((existing?.datetime_formats ?? ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"]).join(", "));
  const [timeFormats, setTimeFormats] = useState((existing?.time_formats ?? ["%H:%M:%S", "%H:%M"]).join(", "));
  const [maps, setMaps] = useState<Record<string, string>>(() =>
    Object.fromEntries(Object.entries(existing?.value_maps ?? {}).map(([f, m]) => [f, Object.entries(m).map(([k, v]) => `${k} = ${v}`).join("\n")])));
  const [checkPeriod, setCheckPeriod] = useState(existing?.check_reporting_period ?? true);
  const [excludes, setExcludes] = useState((existing?.exclude_codes ?? []).join("\n"));
  const [notes, setNotes] = useState("");
  const sample = useAction();
  const save = useAction();

  async function readSample(file: File) {
    const form = new FormData();
    form.append("file", file);
    form.append("dataset_id", ds.dataset_id);
    form.append("source_system", ds.source_system);
    form.append("reporting_date", istIso());
    const r = await sample.run(() => api.upload<InspectResult>("/v1/uploads/inspect", form));
    if (!r) return;
    if (!r.accepted) { sample.setError(r.errors?.join(" ") ?? "File rejected"); return; }
    setColumns(r.columns ?? []);
    setSamples(Object.fromEntries((r.profile ?? []).map((p) => [p.column, p.samples])));
    setMapping((m) => Object.fromEntries(Object.entries(m).filter(([col]) => r.columns?.includes(col))));
  }

  const mappedFields = Object.values(mapping);
  const valueFields = mappedFields.filter((f) => catalog.value_maps[f]);

  function prefill(field: string) {
    const col = Object.keys(mapping).find((c) => mapping[c] === field);
    const vals = col ? samples[col] ?? [] : [];
    const current = maps[field] ?? "";
    const have = new Set(current.split("\n").map((l) => l.split("=")[0].trim()).filter(Boolean));
    const add = vals.filter((s) => !have.has(s)).map((s) => `${s} = `);
    setMaps({ ...maps, [field]: [current, ...add].filter(Boolean).join("\n") });
  }

  async function submit() {
    const definition: SchemaDef = {
      columns: Object.fromEntries(Object.entries(mapping).filter(([, f]) => f)),
      primary_key: pk.filter((f) => mappedFields.includes(f)),
      date_formats: dateFormats.split(",").map((s) => s.trim()).filter(Boolean),
      datetime_formats: dtFormats.split(",").map((s) => s.trim()).filter(Boolean),
      time_formats: timeFormats.split(",").map((s) => s.trim()).filter(Boolean),
      value_maps: Object.fromEntries(valueFields.map((f) => [f, parseMap(maps[f] ?? "", catalog.value_maps[f])]).filter(([, m]) => Object.keys(m).length)),
      check_reporting_period: checkPeriod,
      exclude_codes: excludes.split("\n").map((s) => s.trim()).filter(Boolean),
    };
    const r = await save.run(() => api.post<{ version: number }>(`/v1/datasets/${ds.dataset_id}/schemas`, { definition, notes: notes || null }),
      (res) => `Schema version ${res.version} saved and active.`);
    if (r) onSaved();
  }

  return (
    <Card title={`Column schema: ${ds.dataset_name}`}>
      <p className="muted">
        {existing && <>Current version {ds.schema_version}{ds.schema_notes ? ` — ${ds.schema_notes}` : ""}. </>}
        Upload a real sample file from {ds.source_system.replace("_", " ")}; its columns are read, never assumed. Map each column to an internal field
        (or leave it ignored), then save. Each save creates a new version; earlier uploads keep the version they used.
      </p>
      <Field label="Sample file"><input type="file" accept=".csv,.xlsx" onChange={(e) => e.target.files?.[0] && void readSample(e.target.files[0])} /></Field>
      <ActionMessages error={sample.error} message={null} />
      {columns.length > 0 && (
        <>
          <DataTable rows={columns} rowKey={(c) => c} columns={[
            { header: "File column", render: (c) => <strong>{c}</strong> },
            { header: "Sample values", render: (c) => <span className="muted small">{(samples[c] ?? []).join(" · ")}</span> },
            { header: "Maps to", render: (c) => (
              <select value={mapping[c] ?? ""} onChange={(e) => setMapping({ ...mapping, [c]: e.target.value })}>
                <option value="">(ignore)</option>
                {fields.map((f) => <option key={f.field} value={f.field}>{f.field}{f.required ? " *" : ""} ({f.type})</option>)}
              </select>
            ) },
          ]} />
          <div className="form-grid">
            <Field label="Business key (no duplicates allowed)">
              <div className="checks">
                {mappedFields.filter(Boolean).map((f) => (
                  <label key={f} className="check"><input type="checkbox" checked={pk.includes(f)}
                    onChange={(e) => setPk(e.target.checked ? [...pk, f] : pk.filter((x) => x !== f))} /> {f}</label>
                ))}
              </div>
            </Field>
            <Field label="Date formats" hint="Python strptime, comma separated, e.g. %d-%m-%Y"><input value={dateFormats} onChange={(e) => setDateFormats(e.target.value)} /></Field>
            <Field label="Date-time formats"><input value={dtFormats} onChange={(e) => setDtFormats(e.target.value)} /></Field>
            <Field label="Time formats"><input value={timeFormats} onChange={(e) => setTimeFormats(e.target.value)} /></Field>
          </div>
          {valueFields.map((f) => (
            <Field key={f} label={`Value map for ${f}`} hint={`One per line: source value = ${catalog.value_maps[f].join(" | ")}. Unmapped values stay UNRESOLVED.`}>
              <textarea rows={5} value={maps[f] ?? ""} onChange={(e) => setMaps({ ...maps, [f]: e.target.value })} />
              <button type="button" className="btn btn-ghost btn-small" onClick={() => prefill(f)}>Add sample values</button>
            </Field>
          ))}
          <Field label="Exclude employee codes" hint="One pattern per line (regular expression, case-insensitive), e.g. ^test$ or DUMMY or ^CAND-. Matching rows are skipped and counted.">
            <textarea rows={3} value={excludes} onChange={(e) => setExcludes(e.target.value)} />
          </Field>
          <label className="check"><input type="checkbox" checked={checkPeriod} onChange={(e) => setCheckPeriod(e.target.checked)} /> Reject rows whose date differs from the reporting date (daily datasets)</label>
          <Field label="Change note"><input value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="e.g. defined from Pocket HRMS export of 12-Nov" /></Field>
          <ActionMessages error={save.error} message={save.message} />
          <div className="form-actions"><button className="btn btn-primary" disabled={save.busy} onClick={() => void submit()}>Save schema version</button></div>
        </>
      )}
    </Card>
  );
}

export function DatasetRegistryPage() {
  const datasets = useApi<DatasetInfo[]>("/v1/datasets");
  const catalog = useApi<FieldCatalog>("/v1/datasets/fields");
  const [selected, setSelected] = useState<string | null>(null);
  const { hasPermission } = useAuth();
  const ds = datasets.data?.find((d) => d.dataset_id === selected);
  return (
    <>
      <PageHeader title="Dataset Registry" subtitle="Logical dataset categories and their approved column schemas" />
      {datasets.loading && <Loading />}
      {datasets.error && <ErrorNotice error={datasets.error} />}
      {datasets.data && (
        <DataTable rows={datasets.data} rowKey={(d) => d.dataset_id} columns={[
          { header: "Dataset", render: (d) => <><strong>{d.dataset_name}</strong><div className="muted small">{d.dataset_id}</div></> },
          { header: "Source", render: (d) => d.source_system.replace("_", " ") },
          { header: "Frequency", render: (d) => d.frequency.replace("_", " ") },
          { header: "Schema", render: (d) => <StatusBadge value={d.schema_status} /> },
          { header: "Version", render: (d) => d.schema_version ?? "—" },
          { header: "Mapped columns", render: (d) => (d.schema ? Object.keys(d.schema.columns).length : 0) },
          { header: "", render: (d) => hasPermission("DATA_REGISTRY_MANAGE")
            ? <button className="btn btn-ghost btn-small" onClick={() => setSelected(d.dataset_id)}>{d.schema ? "New version" : "Define"}</button> : null },
        ]} />
      )}
      {ds && catalog.data && <SchemaEditor key={ds.dataset_id + (ds.schema_version ?? 0)} ds={ds} catalog={catalog.data} onSaved={() => { datasets.reload(); }} />}
    </>
  );
}

// ------------------------------------------------------------------ Upload History
export function UploadHistoryPage() {
  const datasets = useApi<DatasetInfo[]>("/v1/datasets");
  const [datasetId, setDatasetId] = useState("");
  const list = useApi<UploadInfo[]>(withQuery("/v1/uploads", { dataset_id: datasetId }));
  const [openId, setOpenId] = useState<number | null>(null);
  const detail = useApi<UploadInfo>(openId ? `/v1/uploads/${openId}` : null);
  return (
    <>
      <PageHeader title="Upload History" subtitle="Every accepted file, its fingerprint and lineage" />
      <Toolbar>
        <Field label="Dataset">
          <select value={datasetId} onChange={(e) => setDatasetId(e.target.value)}>
            <option value="">All datasets</option>
            {datasets.data?.map((d) => <option key={d.dataset_id} value={d.dataset_id}>{d.dataset_name}</option>)}
          </select>
        </Field>
      </Toolbar>
      {list.loading && <Loading />}
      {list.error && <ErrorNotice error={list.error} />}
      {list.data && (
        <DataTable rows={list.data} rowKey={(u) => String(u.upload_id)} columns={[
          { header: "#", render: (u) => <button className="link" onClick={() => setOpenId(u.upload_id)}>{u.upload_id}</button> },
          { header: "Dataset", render: (u) => u.dataset_id },
          { header: "Date", render: (u) => formatDate(u.reporting_date) },
          { header: "File", render: (u) => u.original_filename },
          { header: "Validation", render: (u) => <StatusBadge value={u.validation_status} /> },
          { header: "Rows (valid / invalid)", render: (u) => `${u.valid_rows} / ${u.invalid_rows}` },
          { header: "Current", render: (u) => (u.is_current ? "Yes" : `No${u.superseded_by ? ` (→ #${u.superseded_by})` : ""}`) },
          { header: "By", render: (u) => u.uploaded_by },
          { header: "Uploaded", render: (u) => formatDateTime(u.uploaded_at) },
        ]} />
      )}
      {detail.data && (
        <Card title={`Upload #${detail.data.upload_id} — ${detail.data.original_filename}`}
          actions={<a className="btn btn-ghost" href={apiUrl(`/v1/uploads/${detail.data.upload_id}/exceptions.csv`)}>Download exceptions</a>}>
          <ul className="kv-list">
            <li><span>SHA-256</span><code>{detail.data.sha256}</code></li>
            <li><span>Schema version</span><strong>{detail.data.schema_version}</strong></li>
            <li><span>Standardized records</span><strong>{detail.data.standardized_rows}</strong></li>
            <li><span>Reprocess of</span><strong>{detail.data.reprocess_of ?? "—"}</strong></li>
          </ul>
          {detail.data.issues?.length ? <IssuesTable issues={detail.data.issues} /> : <p className="muted">No validation issues.</p>}
        </Card>
      )}
    </>
  );
}

// ------------------------------------------------------------------ Data Quality
interface DQ {
  uploads: { upload_id: number; dataset_id: string; reporting_date: string; file: string; validation_status: string; total: number; valid: number; invalid: number; duplicates: number; warnings: number; is_current: boolean }[];
  totals: { source_records: number; valid: number; invalid: number; duplicates: number; rejected_uploads: number };
  issues_by_code: Record<string, number>;
  unmapped_employees: number;
  missing_datasets: Record<string, string[]>;
  reconciliation: Record<string, number>;
  unresolved_exceptions: number;
}

export function DataQualityPage() {
  const [end, setEnd] = useState(istIso());
  const [start, setStart] = useState(shiftIso(istIso(), -13));
  const dq = useApi<DQ>(withQuery("/v1/data-quality", { start, end }));
  const missing = useMemo(() => Object.entries(dq.data?.missing_datasets ?? {}).filter(([, v]) => v.length), [dq.data]);
  return (
    <>
      <PageHeader title="Data Quality" subtitle="Validation, mapping and completeness across uploads" />
      <Toolbar>
        <Field label="From"><input type="date" value={start} onChange={(e) => setStart(e.target.value)} /></Field>
        <Field label="To"><input type="date" value={end} onChange={(e) => setEnd(e.target.value)} /></Field>
      </Toolbar>
      {dq.loading && <Loading />}
      {dq.error && <ErrorNotice error={dq.error} />}
      {dq.data && (
        <>
          <div className="kpi-grid">
            <KpiCard label="Source records" value={dq.data.totals.source_records} />
            <KpiCard label="Valid" value={dq.data.totals.valid} />
            <KpiCard label="Invalid" value={dq.data.totals.invalid} />
            <KpiCard label="Duplicates" value={dq.data.totals.duplicates} />
            <KpiCard label="Rejected uploads" value={dq.data.totals.rejected_uploads} />
            <KpiCard label="Unmapped employees" value={dq.data.unmapped_employees} />
            <KpiCard label="Unresolved exceptions" value={dq.data.unresolved_exceptions} />
          </div>
          <div className="grid-2">
            <Card title="Issues by type">
              <DataTable rows={Object.entries(dq.data.issues_by_code)} rowKey={([k]) => k}
                columns={[{ header: "Issue", render: ([k]) => k }, { header: "Count", render: ([, v]) => v }]} />
            </Card>
            <Card title="Missing daily datasets">
              {missing.length ? (
                <DataTable rows={missing} rowKey={([d]) => d} columns={[
                  { header: "Date", render: ([d]) => formatDate(d) }, { header: "Missing", render: ([, v]) => v.join(", ") }]} />
              ) : <p className="muted">None for processed dates in this range.</p>}
            </Card>
          </div>
          <Card title="Uploads in range">
            <DataTable rows={dq.data.uploads} rowKey={(u) => String(u.upload_id)} columns={[
              { header: "#", render: (u) => u.upload_id },
              { header: "Dataset", render: (u) => u.dataset_id },
              { header: "Date", render: (u) => formatDate(u.reporting_date) },
              { header: "Status", render: (u) => <StatusBadge value={u.validation_status} /> },
              { header: "Total", render: (u) => u.total },
              { header: "Invalid", render: (u) => u.invalid },
              { header: "Duplicates", render: (u) => u.duplicates },
              { header: "Warnings", render: (u) => u.warnings },
              { header: "Current", render: (u) => (u.is_current ? "Yes" : "No") },
            ]} />
          </Card>
        </>
      )}
    </>
  );
}
