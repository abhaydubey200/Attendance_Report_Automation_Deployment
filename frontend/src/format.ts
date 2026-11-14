// All display dates are IST (Asia/Kolkata), e.g. 13-Nov-2026.

const DATE = new Intl.DateTimeFormat("en-GB", { timeZone: "Asia/Kolkata", day: "2-digit", month: "short", year: "numeric" });
const TIME = new Intl.DateTimeFormat("en-GB", { timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit", hour12: false });

function dashed(d: Date): string {
  return DATE.format(d).replace(/ /g, "-");
}

/** "2026-11-13" -> "13-Nov-2026" (date-only values are calendar dates, not instants). */
export function formatDate(isoDate: string | null | undefined): string {
  if (!isoDate) return "—";
  const [y, m, d] = isoDate.slice(0, 10).split("-").map(Number);
  return dashed(new Date(Date.UTC(y, m - 1, d, 6, 30)));
}

/** UTC instant -> "13-Nov-2026 14:05 IST". */
export function formatDateTime(isoInstant: string | null | undefined): string {
  if (!isoInstant) return "—";
  const d = new Date(isoInstant);
  if (Number.isNaN(d.getTime())) return "—";
  return `${dashed(d)} ${TIME.format(d)} IST`;
}
