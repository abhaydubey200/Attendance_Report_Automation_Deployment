// Module 2 location checks: the day map, the "Needs checking" case list and the location-history import.
// Wording: "needs checking", never "fraud". Every sign shows its evidence.
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { api } from "../api/client";
import { useAction, useApi } from "../api/useApi";
import { ActionMessages, Card, DataTable, ErrorNotice, Field, KpiCard, Loading, Notice, PageHeader, Toolbar } from "../components/ui";
import { formatDate, formatDateTime } from "../format";
import type { GeoCall, GeoCase, GeoCaseRow, GeoCases, GeoDayMap, GeoLevel, GeoSign } from "./types";
import { DayPhotosCard, PhotoSigns } from "./photos";

const LEVEL_KIND: Record<GeoLevel, "fail" | "warn" | "info"> = { high: "fail", medium: "warn", low: "info" };
const CASE_KIND = { OPEN: "warn", OK: "ok", ACTION: "fail" } as const;
const qs = (o: Record<string, string>) => new URLSearchParams(Object.entries(o).filter(([, v]) => v)).toString();
const t12 = (t: string | null | undefined) => {
  if (!t) return "";
  const [h, m] = t.split(":").map(Number);
  return `${((h + 11) % 12) + 1}:${String(m).padStart(2, "0")} ${h < 12 ? "AM" : "PM"}`;
};
const dist = (m: number | null) => (m === null ? "" : m < 1000 ? `${Math.round(m)} m` : `${(m / 1000).toFixed(1)} km`);
const esc = (s: string) => s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c] as string));

function Signs({ signs }: { signs: GeoSign[] }) {
  return (
    <span className="sales-flags">
      {signs.map((s) => <span key={s.code} className={`badge badge-${LEVEL_KIND[s.level]}`} title={s.evidence || s.why}>{s.label}</span>)}
    </span>
  );
}

// ---------------------------------------------------------------- the map itself
function DayMapView({ m, focus }: { m: GeoDayMap; focus: number | null }) {
  const box = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map | null>(null);
  const callLayers = useRef<Record<number, L.Marker>>({});
  useEffect(() => {
    if (!box.current) return;
    const lm = L.map(box.current, { scrollWheelZoom: false });
    map.current = lm;
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19, attribution: "&copy; OpenStreetMap contributors", referrerPolicy: "strict-origin-when-cross-origin",
    } as L.TileLayerOptions).addTo(lm);
    const bounds: L.LatLngExpression[] = [];
    const pin = (lat: number, lng: number, html: string, cls: string, title: string) => {
      bounds.push([lat, lng]);
      return L.marker([lat, lng], { icon: L.divIcon({ className: `geo-pin ${cls}`, html, iconSize: [26, 26], iconAnchor: [13, 13] }), title })
        .addTo(lm);
    };
    if (m.usual_start) {
      L.circle([m.usual_start.lat, m.usual_start.lng], { radius: m.usual_start.limit_km * 1000, color: "#64748b", weight: 1, dashArray: "4 4", fillOpacity: 0.04 })
        .addTo(lm).bindTooltip(`Usual start (${m.usual_start.days} earlier days) - within ${m.usual_start.limit_km} km is normal`);
      pin(m.usual_start.lat, m.usual_start.lng, "U", "geo-usual", "Usual start point");
    }
    const path: L.LatLngExpression[] = [];
    if (m.attendance) {
      pin(m.attendance.lat, m.attendance.lng, "A", "geo-att", "Attendance").bindPopup(`<b>Attendance</b><br>${t12(m.attendance.time)}`);
      path.push([m.attendance.lat, m.attendance.lng]);
    }
    callLayers.current = {};
    let prev: GeoCall | null = null;
    for (const c of m.calls) {
      if (c.outlet_lat !== null && c.outlet_lng !== null) {
        bounds.push([c.outlet_lat, c.outlet_lng]);
        L.circleMarker([c.outlet_lat, c.outlet_lng], { radius: 5, color: "#b45309", fillColor: "#f59e0b", fillOpacity: 0.9, weight: 1 })
          .addTo(lm).bindTooltip(`Outlet: ${esc(c.outlet ?? "")}`);
      }
      if (c.lat === null || c.lng === null) continue;
      const mk = pin(c.lat, c.lng, String(c.seq), c.away || c.fast ? "geo-call geo-bad" : "geo-call", `Call ${c.seq}`)
        .bindPopup(`<b>${c.seq}. ${esc(c.outlet ?? "")}</b><br>${t12(c.start)} - ${t12(c.end)}${c.beat ? `<br>${esc(c.beat)}` : ""}` +
          `<br>${c.distance_m !== null ? `${dist(c.distance_m)} from the outlet` : ""}${c.productive ? "<br>Order taken" : ""}` +
          (c.leg ? `<br>From previous call: ${c.leg.km} km in ${c.leg.minutes} min (${c.leg.kmh} km/h)` : ""));
      callLayers.current[c.seq] = mk;
      if (c.away && c.outlet_lat !== null && c.outlet_lng !== null) {
        L.polyline([[c.lat, c.lng], [c.outlet_lat, c.outlet_lng]], { color: "#dc2626", weight: 1.5, dashArray: "3 5" }).addTo(lm);
      }
      if (prev && prev.lat !== null && prev.lng !== null && c.fast) {
        L.polyline([[prev.lat, prev.lng], [c.lat, c.lng]], { color: "#dc2626", weight: 4, opacity: 0.6 }).addTo(lm);
      }
      path.push([c.lat, c.lng]);
      prev = c;
    }
    if (m.day_end) {
      pin(m.day_end.lat, m.day_end.lng, "E", "geo-end", "Day end").bindPopup(`<b>Day end</b><br>${t12(m.day_end.time)}`);
      path.push([m.day_end.lat, m.day_end.lng]);
    }
    if (path.length > 1) L.polyline(path, { color: "#14213d", weight: 2, opacity: 0.7 }).addTo(lm);
    // The box only gets its real size once the page has laid out: fit the day's points again whenever the box changes
    // size, until the person moves or zooms the map themselves.
    let moved = false;
    lm.on("dragstart", () => { moved = true; });
    box.current.addEventListener("wheel", () => { moved = true; }, { passive: true });
    const fit = () => {
      lm.invalidateSize({ pan: false });
      if (moved) return;
      if (bounds.length) lm.fitBounds(L.latLngBounds(bounds), { padding: [30, 30], maxZoom: 16, animate: false });
      else lm.setView([22.5, 79], 5, { animate: false });
    };
    fit();
    const ro = new ResizeObserver(() => fit());
    ro.observe(box.current);
    return () => { ro.disconnect(); lm.remove(); map.current = null; };
  }, [m]);
  useEffect(() => {
    const mk = focus !== null ? callLayers.current[focus] : undefined;
    if (mk && map.current) { map.current.setView(mk.getLatLng(), Math.max(map.current.getZoom(), 15)); mk.openPopup(); }
  }, [focus]);
  return <div ref={box} className="geo-map" role="region" aria-label="Map of the day" />;
}

// ---------------------------------------------------------------- day map page
export function SalesMapPage() {
  const [p] = useSearchParams();
  const date = p.get("date") ?? "", code = p.get("code") ?? "";
  const data = useApi<GeoDayMap>(date && code ? `/v1/sales/map/${date}/${encodeURIComponent(code)}` : null);
  const [focus, setFocus] = useState<number | null>(null);
  const m = data.data;
  if (!date || !code) return <><PageHeader title="Day map" /><Notice>Open a person's map from <Link to="/sales/cases">Needs checking</Link> or Day insights.</Notice></>;
  const loc = m?.signs.filter((s) => s.kind === "location") ?? [];
  const day = m?.signs.filter((s) => s.kind === "day") ?? [];
  const photoSigns = [...new Map((m?.photos ?? []).flatMap((p) => p.signs).map((s) => [s.code, s])).values()];
  return (
    <>
      <PageHeader title={m ? `${m.name} · ${formatDate(m.date)}` : "Day map"}
        subtitle={m ? [m.code, m.designation, m.manager && `team head ${m.manager}`, m.hod && `HOD ${m.hod}`].filter(Boolean).join(" · ") : undefined}
        actions={<Toolbar>
          <Link className="btn btn-ghost btn-small" to={`/sales/employee?${qs({ code, end: date })}`}>Employee report</Link>
          <Link className="btn btn-ghost btn-small" to="/sales/cases">All cases</Link>
        </Toolbar>} />
      {data.error && <ErrorNotice error={data.error} />}
      {data.loading || !m ? (data.error ? null : <Loading />) : (
        <>
          <div className="kpi-grid">
            <KpiCard label="Attendance" value={t12(m.attendance_time) || "–"} hint={m.attendance ? "location recorded" : "no location"} />
            <KpiCard label="Calls" value={m.calls.length} hint={`${m.calls.filter((c) => c.productive).length} with an order`} />
            <KpiCard label="KM (Bizom)" value={m.km ?? "–"} />
            <KpiCard label="Day end" value={t12(m.eod_time) || "–"} hint={m.day_end ? "location recorded" : "no location"} />
            <KpiCard label="Location signs" value={loc.length} tone={loc.some((s) => s.level === "high") ? "fail" : loc.length ? "warn" : "ok"} />
          </div>
          <div className="geo-layout">
            <Card title="Map">
              <DayMapView m={m} focus={focus} />
              <div className="geo-legend">
                <span><i className="geo-pin geo-att">A</i> Attendance</span><span><i className="geo-pin geo-call">1</i> Call (in order)</span>
                <span><i className="geo-pin geo-call geo-bad">1</i> Away from outlet / impossible travel</span>
                <span><i className="geo-dot" /> Outlet</span><span><i className="geo-pin geo-end">E</i> Day end</span>
                <span><i className="geo-pin geo-usual">U</i> Usual start</span>
              </div>
              <p className="muted small">The street map needs internet; points and lines come from Bizom. Distances are straight-line.</p>
            </Card>
            <div className="geo-side">
              <Card title="Warning signs — for checking, not proof">
                {loc.length + day.length + photoSigns.length === 0 ? <p className="muted">Nothing to check on this day.</p> : (
                  <ul className="geo-signs">
                    {[...loc, ...photoSigns, ...day].map((s) => (
                      <li key={s.code}><span className={`badge badge-${LEVEL_KIND[s.level]}`}>{s.kind === "location" ? "Location" : s.kind === "photo" ? "Selfie" : "Day"}</span>
                        <div><strong>{s.label}</strong><div className="small">{s.evidence || s.why}</div></div></li>
                    ))}
                  </ul>
                )}
                {m.photo_url && <p><a href={m.photo_url} target="_blank" rel="noreferrer noopener">Open attendance photo ↗</a></p>}
              </Card>
              <ReviewCard date={m.date} code={m.code} initial={m.case} />
            </div>
          </div>
          <DayPhotosCard items={m.photos} />
          <Card title="Day timeline">
            <DataTable rows={m.calls} rowKey={(c) => String(c.seq)} empty="No calls in the Call Variance report for this day." columns={[
              { header: "#", render: (c) => <button type="button" className="link-btn" onClick={() => setFocus(c.seq)}>{c.seq}</button>, value: (c) => c.seq },
              { header: "Time", render: (c) => `${t12(c.start)} – ${t12(c.end)}`, value: (c) => c.start },
              { header: "Outlet", render: (c) => <>{c.outlet}{c.beat && <div className="muted small">{c.beat}</div>}</>, value: (c) => c.outlet },
              { header: "From outlet", render: (c) => <span style={{ color: c.away ? "#b91c1c" : undefined, fontWeight: c.away ? 700 : undefined }}>{dist(c.distance_m)}</span>, value: (c) => c.distance_m },
              { header: "From previous", render: (c) => c.leg ? <span style={{ color: c.fast ? "#b91c1c" : undefined }}>{c.leg.km} km · {c.leg.minutes} min{c.fast ? ` · ${c.leg.kmh} km/h` : ""}</span> : "" },
              { header: "Order", render: (c) => (c.productive ? "Yes" : "") },
            ]} />
          </Card>
        </>
      )}
    </>
  );
}

function ReviewCard({ date, code, initial }: { date: string; code: string; initial: GeoCase }) {
  const [status, setStatus] = useState(initial.status);
  const [note, setNote] = useState(initial.note ?? "");
  const [saved, setSaved] = useState<GeoCase>(initial);
  const { busy, error, message, run } = useAction();
  async function save(e: FormEvent) {
    e.preventDefault();
    const r = await run(() => api.put<GeoCase>(`/v1/sales/cases/${date}/${encodeURIComponent(code)}`, { status, note }), "Review saved.");
    if (r) setSaved(r);
  }
  return (
    <Card title="Review">
      <form onSubmit={save}>
        <Field label="Outcome">
          <select value={status} onChange={(e) => setStatus(e.target.value as GeoCase["status"])}>
            <option value="OPEN">Open – not checked yet</option><option value="OK">Checked – OK</option><option value="ACTION">Action taken</option>
          </select>
        </Field>
        <Field label="Note"><textarea rows={3} value={note} maxLength={1000} onChange={(e) => setNote(e.target.value)} placeholder="What was found when checking" /></Field>
        <ActionMessages error={error} message={message} />
        <Toolbar>
          <button type="submit" className="btn btn-primary btn-small" disabled={busy}>Save</button>
          {saved.reviewed_by && <span className="muted small">Last: {saved.status_label} by {saved.reviewed_by}{saved.reviewed_at ? `, ${formatDateTime(saved.reviewed_at)}` : ""}</span>}
        </Toolbar>
      </form>
    </Card>
  );
}

// ---------------------------------------------------------------- cases list
export function SalesCasesPage() {
  const [p, setP] = useSearchParams();
  const f = { start: p.get("start") ?? "", end: p.get("end") ?? "", status: p.get("status") ?? "OPEN", hod: p.get("hod") ?? "", kind: p.get("kind") ?? "" };
  const set = (o: Partial<typeof f>) => setP(qs({ ...f, ...o }));
  const data = useApi<GeoCases>(`/v1/sales/cases?${qs({ ...f, status: f.status === "ALL" ? "" : f.status })}`);
  const d = data.data;
  return (
    <>
      <PageHeader title="Needs checking" subtitle="People whose day has location or selfie warning signs. Open the day, check with the person, record the outcome."
        actions={<Toolbar>
          <label className="field inline"><span className="field-label">From</span><input type="date" value={f.start || d?.from || ""} onChange={(e) => set({ start: e.target.value })} /></label>
          <label className="field inline"><span className="field-label">To</span><input type="date" value={f.end || d?.to || ""} onChange={(e) => set({ end: e.target.value })} /></label>
        </Toolbar>} />
      <Notice kind="info">Warning signs are for checking, not proof. They show in the app only, not in the emails.</Notice>
      {data.error && <ErrorNotice error={data.error} />}
      {data.loading || !d ? <Loading /> : (
        <Card>
          <Toolbar>
            {[["OPEN", "Open"], ["OK", "Checked – OK"], ["ACTION", "Action taken"], ["ALL", "All"]].map(([k, l]) => (
              <button type="button" key={k} className={`chip-btn${f.status === k ? " on" : ""}`} onClick={() => set({ status: k })}>{l}</button>))}
            <span className="muted small">|</span>
            {[["", "Everything"], ["location", "Location"], ["photos", "Selfies"]].map(([k, l]) => (
              <button type="button" key={`k${k}`} className={`chip-btn${f.kind === k ? " on" : ""}`} onClick={() => set({ kind: k })}>{l}</button>))}
            <label className="field inline"><span className="field-label">HOD</span>
              <select value={f.hod} onChange={(e) => set({ hod: e.target.value })}><option value="">All</option>{d.hods.map((h) => <option key={h}>{h}</option>)}</select></label>
          </Toolbar>
          <DataTable rows={d.cases} rowKey={(c) => `${c.date}|${c.code}`} search exportName={`field_sales_needs_checking_${d.from}_${d.to}`}
            empty="Nobody to check for these filters." columns={[
              { header: "Date", render: (c) => formatDate(c.date), value: (c) => c.date },
              { header: "Employee", render: (c) => <Link to={`/sales/map?${qs({ date: c.date, code: c.code })}`}><strong>{c.name}</strong> <span className="muted">{c.code}</span></Link>, value: (c) => `${c.name} ${c.code}` },
              { header: "Team head", render: (c) => c.manager },
              ...(f.kind === "photos" ? [] : [{ header: "Location signs", render: (c: GeoCaseRow) => <Signs signs={c.signs} />,
                value: (c: GeoCaseRow) => c.signs.map((s) => s.label).join("; ") }]),
              ...(f.kind === "" || f.kind === "photos" ? [{ header: "Selfie signs", render: (c: GeoCaseRow) => <PhotoSigns signs={c.photo_signs} />,
                value: (c: GeoCaseRow) => c.photo_signs.map((s) => s.label).join("; ") }] : []),
              { header: "Other signs", render: (c) => <span className="small">{c.other_signs.join(", ")}</span>, value: (c) => c.other_signs.join("; ") },
              { header: "Review", render: (c) => <><span className={`badge badge-${CASE_KIND[c.case.status]}`}>{c.case.status_label}</span>{c.case.note && <div className="muted small">{c.case.note}</div>}</>, value: (c) => c.case.status_label },
              { header: "", sortable: false, render: (c) => <Link className="btn btn-ghost btn-small" to={`/sales/map?${qs({ date: c.date, code: c.code })}`}>Map</Link> },
            ]} />
        </Card>
      )}
    </>
  );
}

// ---------------------------------------------------------------- history import (upload page)
export function HistoryImportCard() {
  const [file, setFile] = useState<File | null>(null);
  const { busy, error, message, run } = useAction();
  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!file) return;
    const form = new FormData();
    form.append("file", file);
    await run(() => api.upload<{ from: string; to: string; days: number; locations_added: number; phones_added: number; days_rechecked: number }>("/v1/sales/history", form),
      (r) => `${formatDate(r.from)} – ${formatDate(r.to)} (${r.days} days): ${r.locations_added} attendance locations and ${r.phones_added} phone codes added; ${r.days_rechecked} uploaded day(s) checked again.`);
  }
  return (
    <Card title="Location history (optional)">
      <form onSubmit={submit} className="sales-upload">
        <p className="muted">Bizom's multi-day <b>AttendanceReport</b> export (Emp Id, For Date, Attendance Time, IMEI, Location). It teaches the app each
          person's usual start point and adds the phone used, for the "same phone as another person" check. The phone number (IMEI) is stored only as a scrambled code.</p>
        <Field label="AttendanceReport (.csv)"><input type="file" accept=".csv,.xlsx" onChange={(e) => setFile(e.target.files?.[0] ?? null)} /></Field>
        <ActionMessages error={error} message={message} />
        <button type="submit" className="btn btn-primary btn-auto" disabled={busy || !file}>{busy ? "Importing…" : "Import history"}</button>
      </form>
    </Card>
  );
}
