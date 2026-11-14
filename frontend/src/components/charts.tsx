// Small dependency-free SVG charts in the APIS palette. CSP-safe (no inline scripts).

export const STATUS_COLORS: Record<string, string> = {
  PRESENT: "#2e7d4f",
  WORK_FROM_HOME: "#6a9a3a",
  HALF_DAY: "#d7ad5f",
  APPROVED_LEAVE: "#9f7b49",
  PENDING_APPROVAL: "#e0a100",
  MISSING_PUNCH: "#c46a1b",
  ABSENT: "#a52a1a",
  UNRESOLVED: "#7d6e5e",
  WEEKLY_OFF: "#b9aa95",
  HOLIDAY: "#cdbfa9",
};

export const STATUS_LABELS: Record<string, string> = {
  PRESENT: "Present",
  WORK_FROM_HOME: "WFH",
  HALF_DAY: "Half day",
  APPROVED_LEAVE: "Approved leave",
  PENDING_APPROVAL: "Pending approval",
  MISSING_PUNCH: "Missing punch",
  ABSENT: "Absent",
  UNRESOLVED: "Unresolved",
  WEEKLY_OFF: "Weekly off",
  HOLIDAY: "Holiday",
};

export const STATUS_ORDER = Object.keys(STATUS_COLORS);

export interface StackRow {
  label: string;
  counts: Record<string, number>;
}

/** Horizontal stacked bars: one row per item (department, location, date), segments per status. */
export function StackedBars({ rows, title }: { rows: StackRow[]; title: string }) {
  if (!rows.length) return <p className="muted">No data.</p>;
  const labelW = 150;
  const barW = 520;
  const rowH = 30;
  const max = Math.max(1, ...rows.map((r) => Object.values(r.counts).reduce((a, b) => a + b, 0)));
  const used = STATUS_ORDER.filter((s) => rows.some((r) => (r.counts[s] ?? 0) > 0));
  const height = rows.length * rowH + 56;
  return (
    <figure className="chart">
      <svg viewBox={`0 0 ${labelW + barW + 60} ${height}`} role="img" aria-label={title}>
        {rows.map((r, i) => {
          let x = labelW;
          const y = 8 + i * rowH;
          const total = Object.values(r.counts).reduce((a, b) => a + b, 0);
          return (
            <g key={r.label}>
              <text x={labelW - 8} y={y + 15} textAnchor="end" className="chart-label">
                {r.label.length > 22 ? `${r.label.slice(0, 21)}…` : r.label}
              </text>
              {used.map((s) => {
                const v = r.counts[s] ?? 0;
                if (!v) return null;
                const w = (v / max) * barW;
                const rect = (
                  <rect key={s} x={x} y={y} width={Math.max(w - 1, 1)} height={rowH - 10} rx={3} fill={STATUS_COLORS[s]}>
                    <title>{`${r.label}: ${STATUS_LABELS[s]} ${v}`}</title>
                  </rect>
                );
                x += w;
                return rect;
              })}
              <text x={x + 6} y={y + 15} className="chart-value">
                {total}
              </text>
            </g>
          );
        })}
        <g transform={`translate(${labelW}, ${rows.length * rowH + 22})`}>
          {used.map((s, i) => (
            <g key={s} transform={`translate(${(i % 5) * 110}, ${Math.floor(i / 5) * 16})`}>
              <rect width={10} height={10} rx={2} fill={STATUS_COLORS[s]} />
              <text x={14} y={9} className="chart-legend">
                {STATUS_LABELS[s]}
              </text>
            </g>
          ))}
        </g>
      </svg>
      <figcaption>{title}</figcaption>
    </figure>
  );
}

export interface Series {
  name: string;
  color: string;
  values: (number | null)[];
}

/** Line chart over dates. */
export function LineChart({ labels, series, title, unit = "" }: { labels: string[]; series: Series[]; title: string; unit?: string }) {
  if (!labels.length) return <p className="muted">No data.</p>;
  const w = 680;
  const h = 240;
  const left = 44;
  const bottom = 34;
  const all = series.flatMap((s) => s.values.filter((v): v is number => v !== null));
  const max = Math.max(1, ...all);
  const x = (i: number) => left + (labels.length === 1 ? (w - left - 16) / 2 : (i * (w - left - 16)) / (labels.length - 1));
  const y = (v: number) => 12 + (1 - v / max) * (h - bottom - 12);
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => Math.round(f * max * 10) / 10);
  const every = Math.max(1, Math.ceil(labels.length / 8));
  return (
    <figure className="chart">
      <svg viewBox={`0 0 ${w} ${h + 18}`} role="img" aria-label={title}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={left} x2={w - 16} y1={y(t)} y2={y(t)} className="chart-grid" />
            <text x={left - 6} y={y(t) + 4} textAnchor="end" className="chart-value">
              {t}
              {unit}
            </text>
          </g>
        ))}
        {labels.map((l, i) =>
          i % every === 0 || i === labels.length - 1 ? (
            <text key={l} x={x(i)} y={h - bottom + 18} textAnchor="middle" className="chart-label">
              {l}
            </text>
          ) : null,
        )}
        {series.map((s) => {
          const pts = s.values.map((v, i) => (v === null ? null : `${x(i)},${y(v)}`)).filter(Boolean);
          return (
            <g key={s.name}>
              <polyline points={pts.join(" ")} fill="none" stroke={s.color} strokeWidth={2.2} />
              {s.values.map((v, i) =>
                v === null ? null : (
                  <circle key={i} cx={x(i)} cy={y(v)} r={3.5} fill={s.color}>
                    <title>{`${s.name} ${labels[i]}: ${v}${unit}`}</title>
                  </circle>
                ),
              )}
            </g>
          );
        })}
        <g transform={`translate(${left}, ${h + 6})`}>
          {series.map((s, i) => (
            <g key={s.name} transform={`translate(${i * 130}, 0)`}>
              <rect width={10} height={10} rx={2} fill={s.color} />
              <text x={14} y={9} className="chart-legend">
                {s.name}
              </text>
            </g>
          ))}
        </g>
      </svg>
      <figcaption>{title}</figcaption>
    </figure>
  );
}
