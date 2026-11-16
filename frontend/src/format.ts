// All display dates are IST (Asia/Kolkata), e.g. 13-Nov-2026.

const DATE = new Intl.DateTimeFormat("en-GB", { timeZone: "Asia/Kolkata", day: "2-digit", month: "short", year: "numeric" });
const TIME = new Intl.DateTimeFormat("en-US", { timeZone: "Asia/Kolkata", hour: "numeric", minute: "2-digit", hour12: true });

function dashed(d: Date): string {
  return DATE.format(d).replace(/ /g, "-");
}

/** "2026-11-13" -> "13-Nov-2026" (date-only values are calendar dates, not instants). */
export function formatDate(isoDate: string | null | undefined): string {
  if (!isoDate) return "—";
  const [y, m, d] = isoDate.slice(0, 10).split("-").map(Number);
  return dashed(new Date(Date.UTC(y, m - 1, d, 6, 30)));
}

/** Stored 24-hour "HH:MM" -> 12-hour "h:MM AM/PM" (all times are shown in 12-hour format). */
export function formatTime(hhmm: string | null | undefined): string {
  const m = /^(\d{1,2}):(\d{2})/.exec(hhmm ?? "");
  if (!m) return hhmm ?? "";
  const h = Number(m[1]);
  return `${h % 12 || 12}:${m[2]} ${h < 12 ? "AM" : "PM"}`;
}

/** UTC instant -> "13-Nov-2026 2:05 PM IST". */
export function formatDateTime(isoInstant: string | null | undefined): string {
  if (!isoInstant) return "—";
  const d = new Date(isoInstant);
  if (Number.isNaN(d.getTime())) return "—";
  return `${dashed(d)} ${TIME.format(d)} IST`;
}

/** Decimal hours -> "h:mm" (9.47 -> "9:28"). */
export function formatHours(hours: number | null | undefined): string {
  if (hours === null || hours === undefined || Number.isNaN(Number(hours))) return "";
  const m = Math.round(Number(hours) * 60);
  return `${Math.floor(m / 60)}:${String(m % 60).padStart(2, "0")}`;
}
