// HR's yearly holiday list (PDF) - one list for both modules. Module 1 shows the Delhi / Head Office page it uses;
// Module 2 shows every region (each Field Sales person follows the page of their holiday state).
import { useState } from "react";
import { api } from "../api/client";
import { useAction, useApi } from "../api/useApi";
import { useAuth } from "../auth/AuthContext";
import { formatDate } from "../format";
import { ActionMessages, Card, DataTable, Loading, Notice, Toolbar } from "./ui";

export interface HolidayLine { date: string; name: string; day: string; issue: string | null; fixed: boolean }
export interface HolidayRegion { name: string; states: string[]; page: number; holidays: HolidayLine[] }
interface HolidayYear { year: number; file: string | null; uploaded_by: string | null; uploaded_at: string | null; regions: HolidayRegion[];
  head_office: HolidayLine[]; open_issues: number }
interface Preview { year: number; file: string; regions: HolidayRegion[]; open_issues: number;
  issues: (HolidayLine & { region: string })[] }

const statusOf = (h: HolidayLine) => (h.issue && !h.fixed ? "Needs HR" : h.issue ? "Corrected" : "OK");

export function HolidayListCard({ module }: { module: "head-office" | "field-sales" }) {
  const data = useApi<{ years: HolidayYear[]; states: string[] }>("/v1/holidays");
  const { busy, error, message, run } = useAction();
  const { hasPermission } = useAuth();
  const can = hasPermission("MANAGE_SETTINGS");
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [fixing, setFixing] = useState<Record<string, string>>({});
  const [year, setYear] = useState<number | null>(null);

  async function check(f: File | undefined) {
    if (!f) return;
    setFile(f); setPreview(null);
    const form = new FormData(); form.append("file", f);
    await run(() => api.upload<Preview>("/v1/holidays/preview", form), (r) => { setPreview(r); return `Read ${r.regions.length} region(s) for ${r.year} - check below, then save.`; });
  }
  async function save() {
    if (!file) return;
    const form = new FormData(); form.append("file", file);
    await run(() => api.upload<HolidayYear & { field_sales: { days_changed: number } }>("/v1/holidays/upload", form),
      (r) => `Saved the ${r.year} holiday list${r.field_sales?.days_changed ? `; ${r.field_sales.days_changed} Field Sales day(s) recounted` : ""}.`);
    setFile(null); setPreview(null); data.reload();
  }
  async function fix(y: number, region: string, old: string, remove = false) {
    const key = `${region}|${old}`;
    await run(() => api.put(`/v1/holidays/${y}/fix`, { region, old, new: remove ? null : fixing[key] || old }), remove ? "Line removed." : "Date confirmed.");
    data.reload();
  }

  const years = data.data?.years ?? [];
  const cur = years.find((y) => y.year === year) ?? years[0];
  const regions = (cur?.regions ?? []).filter((r) => module === "field-sales" || r.states.includes("Head Office") || r.states.includes("Delhi"));
  const open = (cur?.regions ?? []).flatMap((r) => r.holidays.filter((h) => h.issue && !h.fixed).map((h) => ({ ...h, region: r.name })))
    .filter((h) => module === "field-sales" || regions.some((r) => r.name === h.region));

  return (
    <Card title="Holiday list (HR's yearly PDF)" actions={<Toolbar>
      {years.length > 1 && <select aria-label="Year" value={cur?.year} onChange={(e) => setYear(Number(e.target.value))}>{years.map((y) => <option key={y.year}>{y.year}</option>)}</select>}
      {can && <label className="btn btn-primary btn-small btn-auto">{busy ? "Reading…" : "Upload PDF"}<input type="file" accept=".pdf,application/pdf" hidden onChange={(e) => { void check(e.target.files?.[0]); e.target.value = ""; }} /></label>}
    </Toolbar>}>
      <p className="muted small">{module === "head-office"
        ? "Head Office uses the Delhi / HO page only. Pocket HRMS normally marks these days as holiday; on a listed holiday, anyone it missed is counted as holiday (not absent), and a holiday Pocket HRMS marks that is not on the list is reported."
        : "Each Field Sales person follows the page of their holiday state (Staff list > Holiday state). On their holiday, not marking attendance counts as holiday, not absent."}
        {" "}One upload serves both modules; uploading a year again replaces it.</p>
      <ActionMessages error={error} message={message} />
      {preview && (
        <Notice kind={preview.open_issues ? "warn" : "ok"}>
          <b>{preview.file}</b>: {preview.year}, {preview.regions.length} region(s), {preview.regions.reduce((n, r) => n + r.holidays.length, 0)} holidays.
          {preview.issues.length > 0 && <ul className="plain">{preview.issues.map((i) => <li key={i.region + i.date}><b>{i.region}</b> – {i.name}: {i.issue}</li>)}</ul>}
          {preview.open_issues > 0 && <div className="small">Lines marked "Needs HR" are saved but not used until HR confirms the date below.</div>}
          {" "}<button type="button" className="btn btn-primary btn-small" disabled={busy} onClick={() => void save()}>Save the {preview.year} list</button>{" "}
          <button type="button" className="btn btn-ghost btn-small" onClick={() => { setPreview(null); setFile(null); }}>Cancel</button>
        </Notice>
      )}
      {data.loading ? <Loading /> : !cur ? <p className="muted">No holiday list uploaded yet.</p> : (
        <>
          <p className="small">Saved: <b>{cur.year}</b> from <i>{cur.file}</i>{cur.uploaded_by ? ` by ${cur.uploaded_by}` : ""}.</p>
          {open.length > 0 && (
            <Notice kind="warn"><b>Waiting for HR – not used until confirmed:</b>
              <ul className="plain">{open.map((h) => { const key = `${h.region}|${h.date}`; return (
                <li key={key}>{h.region} – {h.name}: {h.issue}{" "}
                  {can && <><input type="date" aria-label="Correct date" value={fixing[key] ?? h.date} onChange={(e) => setFixing({ ...fixing, [key]: e.target.value })} />{" "}
                    <button type="button" className="btn btn-primary btn-small" disabled={busy} onClick={() => void fix(cur.year, h.region, h.date)}>Confirm date</button>{" "}
                    <button type="button" className="btn btn-ghost btn-small" disabled={busy} onClick={() => void fix(cur.year, h.region, h.date, true)}>Remove</button></>}
                </li>); })}</ul>
            </Notice>
          )}
          {regions.map((r) => (
            <details key={r.name} open={module === "head-office"} className="small" style={{ marginTop: 8 }}>
              <summary><b>{r.name}</b> <span className="muted">({r.holidays.length} holidays · {r.states.join(", ")})</span></summary>
              <DataTable rows={r.holidays} rowKey={(h) => h.date + h.name} columns={[
                { header: "Date", render: (h) => formatDate(h.date), value: (h) => h.date },
                { header: "Day", render: (h) => h.day }, { header: "Holiday", render: (h) => h.name },
                { header: "Check", render: (h) => <span className={`badge badge-${statusOf(h) === "OK" ? "ok" : statusOf(h) === "Corrected" ? "info" : "warn"}`} title={h.issue ?? ""}>{statusOf(h)}</span>,
                  value: (h) => statusOf(h) },
              ]} />
            </details>
          ))}
        </>
      )}
    </Card>
  );
}
