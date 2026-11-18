import { useEffect, useMemo, useRef, useState } from "react";
import { api, apiUrl } from "../api/client";
import { useAction, useApi } from "../api/useApi";
import type { Employee, EmployeeChange, EmployeeList, ImportResult } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { Link } from "react-router-dom";
import { ActionMessages, Card, DataTable, ErrorNotice, Field, Loading, Notice, PageHeader, Toolbar } from "../components/ui";
import { formatDate, formatDateTime } from "../format";

type StatusFilter = "ACTIVE" | "LEFT" | "ALL";
interface Filters {
  q: string;
  hod: string;
  department: string;
  team: string;
  manager: string;
  status: StatusFilter;
}
const NO_FILTERS: Filters = { q: "", hod: "", department: "", team: "", manager: "", status: "ACTIVE" };
const PAGE = 100;
const NONE = "(none)";

/** "Sunil Kumar" - or "Sunil Kumar (sunil.tomar@apisindia.com)" when two HODs share the name. */
function hodLabelOf(name: string, email: string, shared: Set<string>): string {
  if (!name) return "";
  return shared.has(name) ? `${name} (${email.trim().toLowerCase() || "no email"})` : name;
}

const FIELD_LABELS: Record<string, string> = {
  routing_issue: "Routing issue", name: "Name", department: "Department", date_of_joining: "Date of joining", hod_name: "HOD", hod_email: "HOD email",
  team_lead_email: "Team lead email", reporting_manager: "Reporting manager", status: "Status", exit_date: "Last working day",
};

function countBy(rows: Employee[], key: (e: Employee) => string): [string, number][] {
  const m = new Map<string, number>();
  rows.forEach((e) => m.set(key(e) || NONE, (m.get(key(e) || NONE) ?? 0) + 1));
  return [...m.entries()].sort((a, b) => a[0].localeCompare(b[0]));
}

function FilterSelect({ label, value, options, onChange }: { label: string; value: string; options: [string, number][]; onChange: (v: string) => void }) {
  return (
    <Field label={label}>
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">All ({options.reduce((n, [, c]) => n + c, 0)})</option>
        {options.map(([v, c]) => <option key={v} value={v}>{v} ({c})</option>)}
      </select>
    </Field>
  );
}

interface Draft {
  code: string;
  name: string;
  department: string;
  date_of_joining: string;
  hod_name: string;
  hod_email: string;
  team_lead_email: string;
  reporting_manager: string;
  routing_issue: string;
}

function toDraft(e?: Employee): Draft {
  return {
    code: e?.code ?? "", name: e?.name ?? "", department: e?.department ?? "", date_of_joining: e?.date_of_joining ?? "",
    hod_name: e?.hod_name ?? "", hod_email: e?.hod_email ?? "", team_lead_email: e?.team_lead_email ?? "",
    reporting_manager: e?.reporting_manager ?? "",
    routing_issue: e?.routing_issue ?? "",
  };
}

function fmt(v: unknown): string {
  return v === null || v === undefined || v === "" ? "—" : String(v);
}

function EmployeeEditor({ employee, list, canEdit, onDone, onClose }: {
  employee: Employee | null; list: EmployeeList; canEdit: boolean; onDone: (e: Employee, message: string) => void; onClose: () => void;
}) {
  const [d, setD] = useState<Draft>(toDraft(employee ?? undefined));
  const [exitDate, setExitDate] = useState(new Date().toISOString().slice(0, 10));
  const act = useAction();
  const history = useApi<EmployeeChange[]>(employee ? `/v1/employees/${encodeURIComponent(employee.code)}/history` : null);
  // label ("Sunil Kumar (sunil.tomar@...)" for shared names) -> the HOD's name and email
  const hodByLabel = useMemo(() => new Map(list.summary.hods.map((h) => [(h.label ?? h.name).toLowerCase(), h])), [list]);
  const sharedNames = useMemo(() => new Set(list.summary.shared_hod_names ?? []), [list]);
  const [hodText, setHodText] = useState(hodLabelOf(d.hod_name, d.hod_email, sharedNames));
  const managers = useMemo(() => [...new Set(list.employees.map((e) => e.reporting_manager).filter(Boolean))].sort(), [list]);
  const set = (patch: Partial<Draft>) => setD({ ...d, ...patch });
  const top = useRef<HTMLDivElement>(null);
  useEffect(() => top.current?.scrollIntoView?.({ behavior: "smooth", block: "start" }), []);

  function pickHod(text: string) {
    setHodText(text);
    const known = hodByLabel.get(text.trim().toLowerCase());
    if (known) { set({ hod_name: known.name, hod_email: known.email ?? known.emails.join("; ") }); return; }
    // a name two HODs share, typed without picking one: do not guess the email
    set({ hod_name: text, hod_email: sharedNames.has(text.trim()) ? "" : d.hod_email });
  }

  async function save() {
    const body = { ...d, date_of_joining: d.date_of_joining || null };
    const saved = await act.run(() => (employee
      ? api.put<Employee>(`/v1/employees/${encodeURIComponent(employee.code)}`, body)
      : api.post<Employee>("/v1/employees", body)));
    if (saved) onDone(saved, employee ? "Saved." : "Employee added.");
  }

  async function left() {
    if (!employee) return;
    const r = await act.run(() => api.post<Employee>(`/v1/employees/${encodeURIComponent(employee.code)}/left`, { exit_date: exitDate }));
    if (r) onDone(r, `${employee.name} marked as Left. They drop out of reports after ${formatDate(exitDate)}.`);
  }

  async function restore() {
    if (!employee) return;
    const r = await act.run(() => api.post<Employee>(`/v1/employees/${encodeURIComponent(employee.code)}/restore`));
    if (r) onDone(r, `${employee.name} restored.`);
  }

  const ro = !canEdit;
  return (
    <div ref={top}>
    <Card title={employee ? `${employee.name} (${employee.code})` : "Add employee"}
      actions={<button className="btn btn-ghost btn-small" onClick={onClose}>Close</button>}>
      {employee?.status === "LEFT" && (
        <Notice kind="warn">Left · last working day {employee.exit_date ? formatDate(employee.exit_date) : "not set"}. Not included in reports after that date.</Notice>
      )}
      <datalist id="dl-departments">{list.summary.departments.map((x) => <option key={x} value={x} />)}</datalist>
      <datalist id="dl-hods">{list.summary.hods.map((h) => <option key={h.label ?? h.name} value={h.label ?? h.name} />)}</datalist>
      <datalist id="dl-managers">{managers.map((x) => <option key={x} value={x} />)}</datalist>
      <div className="form-grid">
        <Field label="Employee code" hint={employee ? "The code links attendance to this person and cannot be changed." : "Same code as in Pocket HRMS, e.g. SL1234"}>
          <input value={d.code} disabled={!!employee || ro} onChange={(e) => set({ code: e.target.value.toUpperCase() })} />
        </Field>
        <Field label="Employee name"><input value={d.name} disabled={ro} onChange={(e) => set({ name: e.target.value })} /></Field>
        <Field label="Department"><input list="dl-departments" value={d.department} disabled={ro} onChange={(e) => set({ department: e.target.value })} /></Field>
        <Field label="Date of joining"><input type="date" value={d.date_of_joining} disabled={ro} onChange={(e) => set({ date_of_joining: e.target.value })} /></Field>
        <Field label="HOD" hint={sharedNames.has(d.hod_name) ? "Two HODs have this name - pick the one with the right email." : "Pick an existing HOD; their email fills in."}>
          <input list="dl-hods" value={hodText} disabled={ro} onChange={(e) => pickHod(e.target.value)} />
        </Field>
        <Field label="HOD email" hint="Receives this HOD's daily report."><input type="email" value={d.hod_email} disabled={ro} onChange={(e) => set({ hod_email: e.target.value })} /></Field>
        <Field label="Team lead email (Sub split ID)" hint="Blank = reports directly to the HOD.">
          <input type="email" value={d.team_lead_email} disabled={ro} onChange={(e) => set({ team_lead_email: e.target.value })} />
        </Field>
        <Field label="Reporting manager" hint="For information only; the team lead email decides who gets the email.">
          <input list="dl-managers" value={d.reporting_manager} disabled={ro} onChange={(e) => set({ reporting_manager: e.target.value })} />
        </Field>
        <Field label="Routing issue" hint="HOD_EMAIL_CONFLICT holds this person for HR. Clear it once the emails are confirmed.">
          <input value={d.routing_issue} disabled={ro} onChange={(e) => set({ routing_issue: e.target.value.toUpperCase() })} placeholder="none" />
        </Field>
      </div>
      <ActionMessages error={act.error} message={act.message} />
      {canEdit && (
        <div className="form-actions">
          <button className="btn btn-primary btn-inline" disabled={act.busy} onClick={() => void save()}>{employee ? "Save changes" : "Add employee"}</button>
          {employee?.status === "ACTIVE" && (
            <span className="inline-actions">
              <label className="small muted">Last working day <input type="date" value={exitDate} onChange={(e) => setExitDate(e.target.value)} /></label>
              <button className="btn btn-ghost btn-inline danger" disabled={act.busy} onClick={() => void left()}>Mark as Left</button>
            </span>
          )}
          {employee?.status === "LEFT" && (
            <button className="btn btn-ghost btn-inline" disabled={act.busy} onClick={() => void restore()}>Restore</button>
          )}
        </div>
      )}
      {employee && history.data && history.data.length > 0 && (
        <details className="history">
          <summary>Change history ({history.data.length})</summary>
          <ul>
            {history.data.map((h, i) => (
              <li key={i}>
                <strong>{h.action.replace("_", " ").toLowerCase()}</strong> · {formatDateTime(h.at)} · {h.actor}
                {Object.keys(h.changes).length > 0 && (
                  <span className="muted small"> — {Object.entries(h.changes).map(([k, [a, b]]) => `${FIELD_LABELS[k] ?? k}: ${fmt(a)} → ${fmt(b)}`).join("; ")}</span>
                )}
              </li>
            ))}
          </ul>
        </details>
      )}
    </Card>
    </div>
  );
}

export function EmployeesPage() {
  const list = useApi<EmployeeList>("/v1/employees");
  const { hasPermission } = useAuth();
  const canEdit = hasPermission("MANAGE_EMPLOYEES");
  const [f, setF] = useState<Filters>(NO_FILTERS);
  const [limit, setLimit] = useState(PAGE);
  const [editing, setEditing] = useState<Employee | "new" | null>(null);
  const [imported, setImported] = useState<ImportResult | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const importAct = useAction();
  const fileRef = useRef<HTMLInputElement>(null);
  const set = (patch: Partial<Filters>) => { setF({ ...f, ...patch }); setLimit(PAGE); };

  const all = list.data?.employees ?? [];
  const shared = useMemo(() => new Set(list.data?.summary.shared_hod_names ?? []), [list.data]);
  const hodOf = (e: Employee) => hodLabelOf(e.hod_name, e.hod_email, shared);
  const byStatus = useMemo(() => all.filter((e) => f.status === "ALL" || e.status === f.status), [all, f.status]);
  const matches = (e: Employee, skip?: keyof Filters) => {
    const q = f.q.trim().toLowerCase();
    return (skip === "hod" || !f.hod || (hodOf(e) || NONE) === f.hod)
      && (skip === "department" || !f.department || (e.department || NONE) === f.department)
      && (skip === "team" || !f.team || e.team === f.team)
      && (skip === "manager" || !f.manager || (e.reporting_manager || NONE) === f.manager)
      && (!q || [e.code, e.name, e.department, e.hod_name, e.team, e.reporting_manager].some((v) => v.toLowerCase().includes(q)));
  };
  const shown = useMemo(() => byStatus.filter((e) => matches(e)), [byStatus, f]);  // eslint-disable-line react-hooks/exhaustive-deps
  const opts = (key: keyof Filters, get: (e: Employee) => string) => countBy(byStatus.filter((e) => matches(e, key)), get);
  const hodCards = useMemo(() => countBy(byStatus.filter((e) => matches(e, "hod")), hodOf), [byStatus, f, shared]);  // eslint-disable-line react-hooks/exhaustive-deps
  const teams = useMemo(() => (f.hod ? countBy(byStatus.filter((e) => (hodOf(e) || NONE) === f.hod), (e) => e.team) : []), [byStatus, f.hod, shared]);  // eslint-disable-line react-hooks/exhaustive-deps
  const hodInfo = useMemo(() => new Map((list.data?.summary.hods ?? []).map((h) => [h.label ?? h.name, h])), [list.data]);
  const anyFilter = f.q || f.hod || f.department || f.team || f.manager || f.status !== "ACTIVE";

  async function doImport(file: File) {
    const form = new FormData();
    form.append("file", file);
    const r = await importAct.run(() => api.upload<ImportResult>("/v1/employees/import", form));
    if (r) { setImported(r); list.reload(); }
    if (fileRef.current) fileRef.current.value = "";
  }

  if (list.loading && !list.data) return <Loading />;
  if (list.error) return <ErrorNotice error={list.error} />;
  const summary = list.data!.summary;

  return (
    <>
      <PageHeader title="Employees" subtitle="Employee master · HOD → Team → Reporting manager → Employee" />
      <Toolbar>
        <div className="toolbar-actions">
          {canEdit && <button className="btn btn-primary btn-inline" onClick={() => { setEditing("new"); setSaved(null); }}>Add employee</button>}
          {canEdit && (
            <label className="btn btn-ghost btn-inline file-btn">
              {importAct.busy ? "Importing…" : "Import Excel"}
              <input ref={fileRef} type="file" accept=".xlsx,.csv" hidden onChange={(e) => e.target.files?.[0] && void doImport(e.target.files[0])} />
            </label>
          )}
          <a className="btn btn-ghost btn-inline" href={apiUrl("/v1/employees/export")}>Export Excel</a>
        </div>
      </Toolbar>
      <ActionMessages error={importAct.error} message={null} />
      {imported && (
        <Notice kind={imported.problem_count ? "warn" : "ok"}>
          Import: {imported.rows} rows · {imported.added} added · {imported.updated} updated · {imported.unchanged} unchanged
          {imported.kept_left > 0 && ` · ${imported.kept_left} kept as Left`}
          {imported.not_in_file > 0 && ` · ${imported.not_in_file} active employees not in this file (left unchanged)`}
          {imported.routing?.coverage && (
            <><br />Routing workbook: {imported.routing.coverage.differences === 0
              ? `the app's routing matches the Employee_Coverage sheet for all ${imported.routing.coverage.checked} employees ✓`
              : `${imported.routing.coverage.differences} difference(s) with the Employee_Coverage sheet, e.g. ${imported.routing.coverage.examples.slice(0, 3).map((x) => `${x.code}: ${x.issue}`).join("; ")}`}</>
          )}
          {imported.routing?.recipients && <><br />Recipient switches imported: {imported.routing.recipients.imported} ({imported.routing.recipients.switched_off} off).</>}
          {imported.routing?.config && imported.routing.config.disabled.length > 0 && (
            <><br /><strong>Email_Routing_Config switched these off:</strong> {imported.routing.config.disabled.join("; ")}. Turn them on in Settings when the addresses are confirmed.</>
          )}
          {imported.problem_count > 0 && (
            <details><summary>{imported.problem_count} value(s) needed attention</summary>
              <ul className="small">{imported.problems.map((p) => <li key={p}>{p}</li>)}</ul></details>
          )}
        </Notice>
      )}
      {summary.total === 0 && (
        <Notice>No employees yet. Use <strong>Import Excel</strong> with HR's Employee Amendment file (EMPLOYEE CODE, Employee Name, Department, DOJ, HOD, Email ID - HOD, Sub split ID, Reporting Manager).</Notice>
      )}
      {summary.hods_without_email.length > 0 && (
        <Notice kind="warn">No email for HOD {summary.hods_without_email.join(", ")} — they won't receive their report until one is added.</Notice>
      )}

      <ActionMessages error={null} message={saved} />
      {editing && list.data && (
        <EmployeeEditor key={editing === "new" ? "new" : `${editing.code}-${editing.updated_at}`} employee={editing === "new" ? null : editing}
          list={list.data} canEdit={canEdit} onClose={() => { setEditing(null); setSaved(null); }}
          onDone={(e, message) => { setEditing(e); setSaved(message); list.reload(); }} />
      )}

      <div className="kpi-grid kpi-grid-4">
        <div className="kpi-card"><div className="kpi-label">Employees shown</div><div className="kpi-value">{shown.length}</div></div>
        <div className="kpi-card"><div className="kpi-label">HODs</div><div className="kpi-value">{new Set(shown.map(hodOf).filter(Boolean)).size}</div></div>
        <div className="kpi-card"><div className="kpi-label">Departments</div><div className="kpi-value">{new Set(shown.map((e) => e.department).filter(Boolean)).size}</div></div>
        <div className="kpi-card"><div className="kpi-label">Teams</div><div className="kpi-value">{new Set(shown.map((e) => e.team)).size}</div></div>
      </div>

      <Card>
        <div className="filter-grid">
          <Field label="Search"><input className="search" placeholder="Code, name, team, manager…" value={f.q} onChange={(e) => set({ q: e.target.value })} /></Field>
          <FilterSelect label="HOD" value={f.hod} options={opts("hod", hodOf)} onChange={(v) => set({ hod: v, team: "" })} />
          <FilterSelect label="Department" value={f.department} options={opts("department", (e) => e.department)} onChange={(v) => set({ department: v })} />
          <FilterSelect label="Team" value={f.team} options={opts("team", (e) => e.team)} onChange={(v) => set({ team: v })} />
          <FilterSelect label="Reporting manager" value={f.manager} options={opts("manager", (e) => e.reporting_manager)} onChange={(v) => set({ manager: v })} />
          <Field label="Status">
            <select value={f.status} onChange={(e) => set({ status: e.target.value as StatusFilter })}>
              <option value="ACTIVE">Active ({summary.active})</option>
              <option value="LEFT">Left ({summary.left})</option>
              <option value="ALL">All ({summary.total})</option>
            </select>
          </Field>
        </div>
        {anyFilter && <button className="btn btn-ghost btn-small" onClick={() => { setF(NO_FILTERS); setLimit(PAGE); }}>Clear all filters</button>}
      </Card>

      {hodCards.length > 0 && (
        <Card title="HODs">
          <div className="hod-grid">
            {hodCards.map(([name, count]) => {
              const info = hodInfo.get(name);
              return (
                <button key={name} className={`hod-card${f.hod === name ? " on" : ""}`} onClick={() => set({ hod: f.hod === name ? "" : name, team: "" })}>
                  <span className="hod-name">{name}</span>
                  <span className="hod-count">{count}</span>
                  <span className="hod-meta">{info ? `${info.departments.length} dept · ${info.emails[0] ?? "no email"}` : "no HOD assigned"}</span>
                </button>
              );
            })}
          </div>
        </Card>
      )}

      {f.hod && teams.length > 0 && (
        <Card title={`Teams under ${f.hod}`}>
          <div className="chips">
            {teams.map(([t, c]) => (
              <button key={t} className={`chip${f.team === t ? " on" : ""}`} onClick={() => set({ team: f.team === t ? "" : t })}>{t} · {c}</button>
            ))}
          </div>
        </Card>
      )}

      <Card title="Employee list">
        <DataTable rows={shown.slice(0, limit)} rowKey={(e) => e.code} columns={[
          { header: "Code", render: (e) => e.code },
          { header: "Employee", render: (e) => <button className="link" onClick={() => { setEditing(e); setSaved(null); }}>{e.name}</button> },
          { header: "Department", render: (e) => e.department },
          { header: "HOD", render: (e) => hodOf(e) },
          { header: "Team", render: (e) => e.team },
          { header: "Reporting manager", render: (e) => e.reporting_manager },
          { header: "DOJ", render: (e) => (e.date_of_joining ? formatDate(e.date_of_joining) : "") },
          { header: "Status", render: (e) => (
            <>
              {e.status === "LEFT"
                ? <span className="badge badge-warn">Left{e.exit_date ? ` ${formatDate(e.exit_date)}` : ""}</span>
                : <span className="badge badge-ok">Active</span>}
              {e.routing_issue.includes("CONFLICT") && <> <span className="badge badge-fail" title={e.routing_issue}>Held for HR</span></>}
            </>) },
          { header: "", render: (e) => (
            <span className="inline-actions">
              <button className="btn btn-ghost btn-small" onClick={() => { setEditing(e); setSaved(null); }}>{canEdit ? "Edit" : "View"}</button>
              <Link className="btn btn-ghost btn-small" to={`/employee-report?code=${encodeURIComponent(e.code)}`}>Attendance</Link>
            </span>) },
        ]} />
        <div className="form-actions">
          <span className="muted small">Showing {Math.min(limit, shown.length)} of {shown.length}</span>
          {shown.length > limit && <button className="btn btn-ghost btn-small" onClick={() => setLimit(limit + 200)}>Show more</button>}
        </div>
      </Card>
    </>
  );
}
