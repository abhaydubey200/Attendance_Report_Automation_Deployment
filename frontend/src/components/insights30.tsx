// Last-30-report-days views shared by Head Office and Field Sales: trend chart, weekday heatmap, a person's day strip
// and a pop-up with one person's 30 days. Off days (most people on a week off / holiday) are greyed and left out of every %.
import { useEffect, type ReactNode } from "react";

export interface Trend30Day { date: string; label: string; weekday: string; pct: number | null; off_day: boolean; absent: number; late: number | null }

export interface Pack30 {
  labels: string[];
  weekday_of: string[];
  weekdays: string[];
  trend: Trend30Day[];
  heat_all: (number | null)[];
}

/** Code -> [label, colour] for each module's strip letters. */
export type StripLegend = Record<string, [string, string]>;

export const HO_LEGEND: StripLegend = {
  P: ["Present", "#16a34a"], D: ["On duty", "#0d9488"], W: ["Work from home", "#4f46e5"], M: ["Missing punch", "#7c3aed"],
  H: ["Half day", "#f59e0b"], V: ["Leave", "#64748b"], A: ["Absent", "#dc2626"], O: ["Week off / holiday", "#cbd5e1"], N: ["Not tracked", "#e2e8f0"],
};
export const FS_LEGEND: StripLegend = {
  P: ["Present", "#16a34a"], L: ["Late", "#d97706"], H: ["Half day", "#f59e0b"], V: ["Leave", "#64748b"], A: ["Absent", "#dc2626"],
  O: ["Week off", "#cbd5e1"],
};

export const pctColor30 = (v: number | null | undefined) =>
  v === null || v === undefined ? "#e5e7eb" : v >= 90 ? "#16a34a" : v >= 80 ? "#65a30d" : v >= 70 ? "#d97706" : v >= 50 ? "#ea580c" : "#dc2626";

/** Attendance % line (working days) over absent-people bars; off days shaded grey. */
export function Trend30({ trend, title = "Last 30 report days" }: { trend: Trend30Day[]; title?: string }) {
  if (trend.length < 2) return <p className="muted">Upload more days to see the trend.</p>;
  const W = 680, H = 220, L = 40, R = 12, top = 10, bot = 34, n = trend.length;
  const x = (i: number) => L + (i * (W - L - R)) / (n - 1);
  const y = (v: number) => top + ((100 - v) * (H - top - bot)) / 100;
  const maxA = Math.max(1, ...trend.map((t) => t.absent));
  const bw = Math.max(3, ((W - L - R) / n) * 0.55);
  const every = Math.ceil(n / 10);
  const segs: string[] = [];
  trend.forEach((t, i) => {
    if (t.pct === null) return;
    const prev = trend[i - 1];
    segs.push(`${prev && prev.pct !== null ? "L" : "M"}${x(i).toFixed(1)} ${y(t.pct).toFixed(1)}`);
  });
  const vals = trend.filter((t) => t.pct !== null).map((t) => t.pct as number);
  const avg = vals.length ? Math.round((10 * vals.reduce((a, b) => a + b, 0)) / vals.length) / 10 : null;
  return (
    <figure className="chart">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={title}>
        {[50, 75, 90, 100].map((g) => (
          <g key={g}>
            <line x1={L} x2={W - R} y1={y(g)} y2={y(g)} className="chart-grid" stroke={g === 90 ? "#bbf7d0" : undefined} />
            <text x={L - 6} y={y(g) + 4} textAnchor="end" className="chart-value">{g}%</text>
          </g>
        ))}
        {trend.map((t, i) => (
          <g key={t.date}>
            {t.off_day && <rect x={x(i) - bw / 2} y={top} width={bw} height={H - top - bot} fill="#f1f5f9"><title>{`${t.label} (${t.weekday}): off day – left out`}</title></rect>}
            <rect x={x(i) - bw / 2} y={H - bot - (t.absent / maxA) * 42} width={bw} height={(t.absent / maxA) * 42} fill="#fecaca">
              <title>{`${t.label}: ${t.absent} absent`}</title></rect>
            {(i % every === 0 || i === n - 1) && <text x={x(i)} y={H - 12} textAnchor="middle" className="chart-label">{t.label}</text>}
          </g>
        ))}
        <path d={segs.join("")} fill="none" stroke="#14213d" strokeWidth={2.2} />
        {trend.map((t, i) => (t.pct === null ? null : (
          <circle key={t.date} cx={x(i)} cy={y(t.pct)} r={i === n - 1 ? 5 : 3.6} fill={pctColor30(t.pct)} stroke="#fff">
            <title>{`${t.label} (${t.weekday}): ${t.pct}% · ${t.absent} absent${t.late !== null ? ` · ${t.late} late` : ""}`}</title>
          </circle>
        )))}
      </svg>
      <figcaption>
        {avg !== null && <>Average on working days <b>{avg}%</b> · best {Math.max(...vals)}% · lowest {Math.min(...vals)}%. </>}
        Red bars = absent people; grey = off day (left out).
      </figcaption>
    </figure>
  );
}

export interface HeatRow { name: string; heat: (number | null)[]; extra?: ReactNode; onClick?: () => void }

/** Rows x weekdays, coloured by attendance %. */
export function WeekdayHeat({ weekdays, rows, extraHeader, note }: { weekdays: string[]; rows: HeatRow[]; extraHeader?: string; note?: string }) {
  const show = weekdays.map((_, k) => rows.some((r) => r.heat[k] !== null && r.heat[k] !== undefined));
  return (
    <div className="heat30-wrap">
      <table className="heat30">
        <thead><tr><th />{weekdays.map((w, k) => (show[k] ? <th key={w}>{w}</th> : null))}{extraHeader && <th>{extraHeader}</th>}</tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.name} className={r.onClick ? "click" : ""} onClick={r.onClick} title={r.onClick ? `Show ${r.name}` : undefined}>
              <td className="nm">{r.name}</td>
              {r.heat.map((v, k) => (show[k] ? (
                <td key={k} className="hc" style={{ background: v === null ? "#f8fafc" : pctColor30(v), color: v === null ? "#94a3b8" : "#fff" }}
                  title={`${r.name} · ${weekdays[k]}: ${v === null ? "no working days" : `${v}%`}`}>{v === null ? "–" : Math.round(v)}</td>
              ) : null))}
              {extraHeader && <td className="num">{r.extra}</td>}
            </tr>
          ))}
        </tbody>
      </table>
      {note && <p className="muted small">{note}</p>}
    </div>
  );
}

/** A person's day-by-day strip; `mini` is the compact version for table cells. */
export function Strip30({ strip, pack, legend, mini = false }: { strip: string; pack: Pack30; legend: StripLegend; mini?: boolean }) {
  return (
    <span className={mini ? "strip30 mini" : "strip30"} aria-label="Last report days">
      {strip.split("").map((c, i) => (
        <i key={i} style={{ background: legend[c]?.[1] ?? "#eef1f6" }} title={`${pack.labels[i]} ${pack.weekday_of[i]}: ${legend[c]?.[0] ?? "No record"}`}>
          {mini ? null : (pack.labels[i] || "").split("-")[0]}
        </i>
      ))}
    </span>
  );
}

export function Legend30({ legend }: { legend: StripLegend }) {
  return <div className="leg30">{Object.entries(legend).map(([k, [l, c]]) => <span key={k}><i style={{ background: c }} />{l}</span>)}</div>;
}

/** Pop-up with one person's last 30 report days. */
export function Person30({ title, subtitle, facts, strip, pack, legend, onClose, children }: {
  title: string; subtitle?: string; facts: [string, ReactNode][]; strip: string; pack: Pack30; legend: StripLegend; onClose: () => void; children?: ReactNode;
}) {
  useEffect(() => {
    const k = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose]);
  return (
    <div className="modal-scrim" onClick={onClose}>
      <div className="modal person30" role="dialog" aria-modal="true" aria-label={title} onClick={(e) => e.stopPropagation()}>
        <button type="button" className="x" onClick={onClose} aria-label="Close">✕</button>
        <h3>{title}</h3>
        {subtitle && <p className="muted small" style={{ marginTop: 0 }}>{subtitle}</p>}
        <div className="facts30">{facts.map(([k, v]) => <div key={k}><span>{k}</span><b>{v === null || v === undefined || v === "" ? "–" : v}</b></div>)}</div>
        <Strip30 strip={strip} pack={pack} legend={legend} />
        <Legend30 legend={legend} />
        {children}
      </div>
    </div>
  );
}
