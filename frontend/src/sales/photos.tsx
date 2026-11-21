// Module 2 selfie checks: the Selfie checks page and the photos card on the day page.
// Photos are shown straight from Bizom's image server; the HR Portal keeps only fingerprints.
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import { useAction, useApi } from "../api/useApi";
import { useAuth } from "../auth/AuthContext";
import { ActionMessages, Card, ErrorNotice, KpiCard, Loading, Notice, PageHeader, Toolbar } from "../components/ui";
import { formatDate } from "../format";
import type { GeoLevel, GeoSign, PhotoItem, PhotosOverview } from "./types";

const LEVEL_KIND: Record<GeoLevel, "fail" | "warn" | "info"> = { high: "fail", medium: "warn", low: "info" };
const qs = (o: Record<string, string>) => new URLSearchParams(Object.entries(o).filter(([, v]) => v)).toString();

export function PhotoSigns({ signs }: { signs: GeoSign[] }) {
  return (
    <span className="sales-flags">
      {signs.map((s) => <span key={s.code} className={`badge badge-${LEVEL_KIND[s.level]}`} title={s.evidence || s.why}>{s.label}</span>)}
    </span>
  );
}

function Thumb({ url, caption, to }: { url: string; caption: string; to?: string }) {
  const img = <img src={url} alt={caption} loading="lazy" referrerPolicy="no-referrer" />;
  return (
    <figure className="photo-thumb">
      <a href={url} target="_blank" rel="noreferrer noopener" title="Open the full photo">{img}</a>
      <figcaption>{to ? <Link to={to}>{caption}</Link> : caption}</figcaption>
    </figure>
  );
}

function PhotoRow({ p }: { p: PhotoItem }) {
  return (
    <div className="photo-row">
      <div className="photo-pair">
        <Thumb url={p.url} caption={`${p.name} · ${formatDate(p.date)}`} to={`/sales/map?${qs({ date: p.date, code: p.code })}`} />
        {p.matches.map((m) => <Thumb key={m.id} url={m.url} caption={`${m.name} · ${formatDate(m.date)}`} to={`/sales/map?${qs({ date: m.date, code: m.code })}`} />)}
      </div>
      <div className="photo-info">
        <PhotoSigns signs={p.signs} />
        {p.signs.map((s) => s.evidence && <span key={s.code} className="cell-sub">{s.evidence}</span>)}
        <span className="cell-sub">{p.code}{p.att_time ? ` · attendance ${p.att_time}` : ""}{p.width ? ` · ${p.width}×${p.height}, ${p.size_kb} KB` : ""}
          {p.faces !== null ? ` · faces found: ${p.faces}` : ""}</span>
      </div>
    </div>
  );
}

export function SalesPhotosPage() {
  const [p, setP] = useSearchParams();
  const f = { start: p.get("start") ?? "", end: p.get("end") ?? "", sign: p.get("sign") ?? "" };
  const set = (o: Partial<typeof f>) => setP(qs({ ...f, ...o }));
  const data = useApi<PhotosOverview>(`/v1/sales/photos?${qs(f)}`);
  const { busy, error, message, run } = useAction();
  const { hasPermission } = useAuth();
  const d = data.data;
  async function checkNow() {
    await run(() => api.post<{ fetched: number; done?: number; failed?: number; flagged?: number }>("/v1/sales/photos/run", { limit: 300 }),
      (r) => `Checked ${r.fetched} photos (${r.done ?? 0} done, ${r.failed ?? 0} failed). ${r.flagged ?? 0} need checking in total.`);
    data.reload();
  }
  return (
    <>
      <PageHeader title="Selfie checks" subtitle="Attendance selfies compared with each other and checked for a face, a camera date and quality."
        actions={<Toolbar>
          <label className="field inline"><span className="field-label">From</span><input type="date" value={f.start || d?.from || ""} onChange={(e) => set({ start: e.target.value })} /></label>
          <label className="field inline"><span className="field-label">To</span><input type="date" value={f.end || d?.to || ""} onChange={(e) => set({ end: e.target.value })} /></label>
          {hasPermission("UPLOAD_AND_SEND") && <button type="button" className="btn btn-ghost btn-small" disabled={busy} onClick={() => void checkNow()}>{busy ? "Checking…" : "Check waiting photos now"}</button>}
        </Toolbar>} />
      <Notice kind="info">Photos are shown from Bizom's server; the HR Portal keeps only a fingerprint of each, for 6 months. A sign is something to check, not proof.</Notice>
      <ActionMessages error={error} message={message} />
      {data.error && <ErrorNotice error={data.error} />}
      {data.loading || !d ? <Loading /> : (
        <>
          <div className="kpi-grid">
            <KpiCard label="Selfies in period" value={d.photos.toLocaleString("en-IN")} hint={`${d.checked.toLocaleString("en-IN")} checked`} />
            <KpiCard label="Need checking" value={d.flagged} tone={d.flagged ? "warn" : "ok"} hint={`${d.people} people`} />
            <KpiCard label="Waiting to be checked" value={d.queue.waiting.toLocaleString("en-IN")} hint="checked by the daily job" />
            <KpiCard label="Could not open" value={d.queue.failed + d.queue.skipped} hint="link gone or not a photo" />
          </div>
          <Card title="Warning signs — click one to filter">
            {d.signs.length === 0 ? <p className="muted">Nothing to check in this period.</p> : (
              <ul className="sales-warn">
                {d.signs.map((s) => (
                  <li key={s.code}><button type="button" className={f.sign === s.code ? "on" : ""} title={s.why} onClick={() => set({ sign: f.sign === s.code ? "" : s.code })}>
                    <i className={`lv-${s.level}`} /> <span>{s.label}</span> <b>{s.n}</b></button></li>
                ))}
              </ul>
            )}
          </Card>
          <Card title={`Selfies to check${d.shown > d.items.length ? ` – first ${d.items.length} of ${d.shown}` : ""}`}>
            {d.items.length === 0 ? <p className="muted">Nothing to show.</p> : d.items.map((x) => <PhotoRow key={x.id} p={x} />)}
          </Card>
        </>
      )}
    </>
  );
}

export function DayPhotosCard({ items }: { items: PhotoItem[] }) {
  if (!items.length) return null;
  return (
    <Card title="Attendance selfie">
      {items.map((x) => x.status === "DONE" ? <PhotoRow key={x.id} p={x} />
        : <p key={x.id} className="muted small">Selfie {x.status === "NEW" ? "not checked yet" : `could not be opened (${x.error ?? x.status})`} – <a href={x.url} target="_blank" rel="noreferrer noopener">open ↗</a></p>)}
    </Card>
  );
}
