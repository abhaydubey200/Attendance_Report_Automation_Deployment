// Module 2 expense claim checks: the claims page, the claims card on the day map and the claim import.
// Wording: "needs checking", never "fraud". Every sign shows its evidence.
import { useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import { useAction, useApi } from "../api/useApi";
import { ActionMessages, Card, DataTable, ErrorNotice, Field, KpiCard, Loading, Notice, PageHeader, Toolbar } from "../components/ui";
import { formatDate } from "../format";
import type { ClaimLine, ClaimsOverview, GeoLevel, GeoSign } from "./types";

const LEVEL_KIND: Record<GeoLevel, "fail" | "warn" | "info"> = { high: "fail", medium: "warn", low: "info" };
const rs = (n: number | null | undefined) => (n === null || n === undefined ? "" : `Rs ${Math.round(n).toLocaleString("en-IN")}`);
const qs = (o: Record<string, string>) => new URLSearchParams(Object.entries(o).filter(([, v]) => v)).toString();
const IMG_LABEL: Record<string, string> = { document: "Document", bill_1: "Bill", bill_2: "Bill 2", odometer_start: "Odometer start", odometer_end: "Odometer end" };

export function ClaimSigns({ signs }: { signs: GeoSign[] }) {
  return (
    <span className="sales-flags">
      {signs.map((s) => <span key={s.code} className={`badge badge-${LEVEL_KIND[s.level]}`} title={s.evidence || s.why}>{s.label}</span>)}
    </span>
  );
}

function Photos({ images }: { images: Record<string, string> }) {
  const keys = Object.keys(images);
  if (!keys.length) return null;
  return <span className="small">{keys.map((k, i) => <span key={k}>{i ? " · " : ""}<a href={images[k]} target="_blank" rel="noreferrer noopener">{IMG_LABEL[k] ?? k} ↗</a></span>)}</span>;
}

// ---------------------------------------------------------------- claims page
export function SalesClaimsPage() {
  const [p, setP] = useSearchParams();
  const f = { start: p.get("start") ?? "", end: p.get("end") ?? "", sign: p.get("sign") ?? "", q: p.get("q") ?? "" };
  const set = (o: Partial<typeof f>) => setP(qs({ ...f, ...o }));
  const data = useApi<ClaimsOverview>(`/v1/sales/claims?${qs(f)}`);
  const d = data.data;
  return (
    <>
      <PageHeader title="Expense claims" subtitle="Bizom claim lines checked against attendance, market activity, location and the other claims."
        actions={<Toolbar>
          <label className="field inline"><span className="field-label">From</span><input type="date" value={f.start || d?.from || ""} onChange={(e) => set({ start: e.target.value })} /></label>
          <label className="field inline"><span className="field-label">To</span><input type="date" value={f.end || d?.to || ""} onChange={(e) => set({ end: e.target.value })} /></label>
          <Link className="btn btn-ghost btn-small" to="/sales/upload">Import claims</Link>
        </Toolbar>} />
      <Notice kind="info">Warning signs are for checking with the person and the approver, not proof. Check the evidence and the photos before acting.</Notice>
      {data.error && <ErrorNotice error={data.error} />}
      {data.loading || !d ? <Loading /> : d.lines === 0 ? (
        <Card title="No claims for this period"><p>Import Bizom's <b>Claim report</b> on the <Link to="/sales/upload">Upload</Link> page.</p></Card>
      ) : (
        <>
          <div className="kpi-grid">
            <KpiCard label="Claimed" value={rs(d.amount)} hint={`${d.lines.toLocaleString("en-IN")} claim lines · ${formatDate(d.from)} – ${formatDate(d.to)}`} />
            <KpiCard label="Lines to check" value={d.flagged_lines.toLocaleString("en-IN")} tone={d.flagged_lines ? "warn" : "ok"} hint={`${Math.round((100 * d.flagged_lines) / d.lines)}% of lines`} />
            <KpiCard label="Amount to check" value={rs(d.flagged_amount)} tone="fail" hint={`${Math.round((100 * d.flagged_amount) / Math.max(1, d.amount))}% of claimed`} />
            <KpiCard label="People" value={d.people} hint="with a claim to check" />
          </div>
          <Card title="Warning signs — click one to filter">
            <ul className="sales-warn">
              {d.signs.map((s) => (
                <li key={s.code}><button type="button" className={f.sign === s.code ? "on" : ""} title={s.why} onClick={() => set({ sign: f.sign === s.code ? "" : s.code })}>
                  <i className={`lv-${s.level}`} /> <span>{s.label}</span> <b style={{ whiteSpace: "nowrap" }}>{s.n} · {rs(s.amount)}</b></button></li>
              ))}
            </ul>
          </Card>
          <Card title={`Claim lines to check${f.sign ? ` – ${d.signs.find((s) => s.code === f.sign)?.label ?? ""}` : ""}`}>
            <Toolbar>
              <input type="search" placeholder="Find a person or code…" defaultValue={f.q} aria-label="Find a person"
                onKeyDown={(e) => { if (e.key === "Enter") set({ q: (e.target as HTMLInputElement).value }); }} />
              {d.shown > d.claims.length && <span className="muted small">Showing the first {d.claims.length} of {d.shown}. Filter to narrow down.</span>}
            </Toolbar>
            <DataTable rows={d.claims} rowKey={(c) => c.id} exportName={`field_sales_claims_${d.from}_${d.to}`} columns={[
              { header: "Date", render: (c) => formatDate(c.date), value: (c) => c.date },
              { header: "Employee", render: (c) => <Link to={`/sales/map?${qs({ date: c.date, code: c.code })}`}><strong>{c.name}</strong> <span className="muted">{c.code}</span></Link>, value: (c) => `${c.name} ${c.code}` },
              { header: "Claim", render: (c) => <>{c.type}<span className="cell-sub">{[c.present_type, c.mode, c.from && `${c.from} → ${c.to}`].filter(Boolean).join(" · ")}</span></>, value: (c) => c.type },
              { header: "Amount", render: (c) => <strong>{rs(c.amount)}</strong>, value: (c) => c.amount },
              { header: "Signs", render: (c) => <><ClaimSigns signs={c.signs} />{c.signs.map((s) => s.evidence && <span key={s.code} className="cell-sub">{s.evidence}</span>)}</>,
                value: (c) => c.signs.map((s) => `${s.label}: ${s.evidence}`).join("; ") },
              { header: "Approval", render: (c) => <span className="small">{c.status}</span>, value: (c) => c.status },
              { header: "Photos", sortable: false, render: (c) => <Photos images={c.images} /> },
            ]} />
          </Card>
        </>
      )}
    </>
  );
}

// ---------------------------------------------------------------- claims of one day (day map page)
export function DayClaimsCard({ claims }: { claims: ClaimLine[] }) {
  if (!claims.length) return null;
  const total = claims.reduce((a, c) => a + c.amount, 0);
  return (
    <Card title={`Claims that day – ${rs(total)}`}>
      <DataTable rows={claims} rowKey={(c) => c.id} columns={[
        { header: "Claim", render: (c) => <>{c.type}<span className="cell-sub">{[c.present_type, c.mode, c.from && `${c.from} → ${c.to}`].filter(Boolean).join(" · ")}</span></>, value: (c) => c.type },
        { header: "Amount", render: (c) => rs(c.amount), value: (c) => c.amount },
        { header: "Signs", render: (c) => <><ClaimSigns signs={c.signs} />{c.signs.map((s) => s.evidence && <span key={s.code} className="cell-sub">{s.evidence}</span>)}</>,
          value: (c) => c.signs.map((s) => s.label).join("; ") },
        { header: "Approval", render: (c) => <span className="small">{c.status}</span> },
        { header: "Photos", sortable: false, render: (c) => <Photos images={c.images} /> },
      ]} />
    </Card>
  );
}

// ---------------------------------------------------------------- import (upload page)
export function ClaimsImportCard() {
  const [file, setFile] = useState<File | null>(null);
  const { busy, error, message, run } = useAction();
  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!file) return;
    const form = new FormData();
    form.append("file", file);
    await run(() => api.upload<{ from: string; to: string; rows: number; added: number; updated: number; flagged_lines: number; flagged_amount: number }>("/v1/sales/claims/import", form),
      (r) => `${formatDate(r.from)} – ${formatDate(r.to)}: ${r.rows} claim lines (${r.added} new, ${r.updated} updated). ${r.flagged_lines} lines to check (${rs(r.flagged_amount)}).`);
  }
  return (
    <Card title="Expense claims (optional)">
      <form onSubmit={submit} className="sales-upload">
        <p className="muted">Bizom's <b>Claim report</b> (APISCLAIMReport, any number of days). Each claim line is checked against the day's attendance, market
          activity, location and the other claims. Import it again any time - existing lines are updated, never doubled.
          For the attendance checks, import the <b>Location history</b> for the same days first.</p>
        <Field label="Claim report (.csv)"><input type="file" accept=".csv,.xlsx" onChange={(e) => setFile(e.target.files?.[0] ?? null)} /></Field>
        <ActionMessages error={error} message={message} />
        <button type="submit" className="btn btn-primary btn-auto" disabled={busy || !file}>{busy ? "Checking claims…" : "Import claims"}</button>
      </form>
    </Card>
  );
}
