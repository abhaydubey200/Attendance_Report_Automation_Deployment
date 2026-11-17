// Small dependency-free SVG charts in the APIS palette.

export const STATUS_COLORS: Record<string, string> = {
  PRESENT: "#16a34a",
  MISSING_PUNCH: "#7c3aed",
  ON_DUTY: "#0d9488",
  WFH: "#4f46e5",
  WEEK_OFF: "#94a3b8",
  HOLIDAY: "#f59e0b",
  HALF_DAY: "#d97706",
  LEAVE: "#64748b",
  ABSENT: "#dc2626",
  NOT_TRACKED: "#cbd5e1",
};

export const STATUS_LABELS: Record<string, string> = {
  PRESENT: "Present",
  MISSING_PUNCH: "Missing punch",
  ON_DUTY: "On duty",
  WFH: "Work from home",
  WEEK_OFF: "Week off",
  HOLIDAY: "Holiday",
  HALF_DAY: "Half day",
  LEAVE: "Leave",
  ABSENT: "Absent",
  NOT_TRACKED: "Not tracked",
};

export interface Bar {
  label: string;
  value: number;
  color: string;
}

/** Horizontal bars, one per item. `max` fixes the scale (e.g. 100 for percentages). */
export function HBars({ bars, title, max, unit = "" }: { bars: Bar[]; title: string; max?: number; unit?: string }) {
  if (!bars.length) return <p className="muted">No data.</p>;
  const labelW = 130;
  const barW = 380;
  const rowH = 28;
  const top = max ?? Math.max(1, ...bars.map((b) => b.value));
  return (
    <figure className="chart">
      <svg viewBox={`0 0 ${labelW + barW + 70} ${bars.length * rowH + 6}`} role="img" aria-label={title}>
        {bars.map((b, i) => {
          const w = Math.max(2, (b.value / top) * barW);
          const y = 4 + i * rowH;
          return (
            <g key={b.label}>
              <text x={labelW - 8} y={y + 15} textAnchor="end" className="chart-label">
                {b.label}
              </text>
              <rect x={labelW} y={y} width={w} height={rowH - 10} rx={4} fill={b.color}>
                <title>{`${b.label}: ${b.value}${unit}`}</title>
              </rect>
              <text x={labelW + w + 6} y={y + 14} className="chart-value">
                {b.value}
                {unit}
              </text>
            </g>
          );
        })}
      </svg>
      <figcaption>{title}</figcaption>
    </figure>
  );
}

/** Line chart over dates (attendance trend). */
export function LineChart({ labels, values, title, unit = "", color = "#14213d" }: { labels: string[]; values: (number | null)[]; title: string; unit?: string; color?: string }) {
  if (labels.length < 2) return <p className="muted">Upload more days to see the trend.</p>;
  const w = 680;
  const h = 220;
  const left = 44;
  const bottom = 30;
  const nums = values.filter((v): v is number => v !== null);
  const lo = Math.max(0, Math.floor(Math.min(...nums) / 10) * 10 - 10);
  const hi = Math.min(100, Math.ceil(Math.max(...nums) / 10) * 10 + 5);
  const x = (i: number) => left + (i * (w - left - 16)) / (labels.length - 1);
  const y = (v: number) => 10 + (1 - (v - lo) / Math.max(1, hi - lo)) * (h - bottom - 10);
  const ticks = [lo, (lo + hi) / 2, hi].map((t) => Math.round(t));
  const every = Math.max(1, Math.ceil(labels.length / 8));
  const pts = values.map((v, i) => (v === null ? null : `${x(i)},${y(v)}`)).filter(Boolean).join(" ");
  return (
    <figure className="chart">
      <svg viewBox={`0 0 ${w} ${h}`} role="img" aria-label={title}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={left} x2={w - 16} y1={y(t)} y2={y(t)} className="chart-grid" />
            <text x={left - 6} y={y(t) + 4} textAnchor="end" className="chart-value">{t}{unit}</text>
          </g>
        ))}
        {labels.map((l, i) => (i % every === 0 || i === labels.length - 1 ? (
          <text key={l} x={x(i)} y={h - bottom + 18} textAnchor="middle" className="chart-label">{l}</text>
        ) : null))}
        <polyline points={pts} fill="none" stroke={color} strokeWidth={2.4} />
        {values.map((v, i) => (v === null ? null : (
          <circle key={i} cx={x(i)} cy={y(v)} r={3.8} fill={color}><title>{`${labels[i]}: ${v}${unit}`}</title></circle>
        )))}
      </svg>
      <figcaption>{title}</figcaption>
    </figure>
  );
}
