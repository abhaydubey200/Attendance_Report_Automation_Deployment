import { formatDate, formatDateTime, formatHours, formatTime } from "./format";

test("formats calendar dates without timezone drift", () => {
  expect(formatDate("2026-11-13")).toBe("13-Nov-2026");
  expect(formatDate("2026-01-01")).toBe("01-Jan-2026");
  expect(formatDate("2026-09-30")).toBe("30-Sep-2026");          // never "Sept" (the browser's own short name)
  expect(formatDate(null)).toBe("—");
});

test("formats UTC instants in IST", () => {
  expect(formatDateTime("2026-11-13T20:00:00Z")).toBe("14-Nov-2026 1:30 AM IST");
  expect(formatTime("09:05")).toBe("9:05 AM");
  expect(formatTime("13:40")).toBe("1:40 PM");
  expect(formatTime("00:15")).toBe("12:15 AM");
  expect(formatTime(null)).toBe("");
  expect(formatHours(9.47)).toBe("9:28");
  expect(formatHours(8.6)).toBe("8:36");
  expect(formatHours(null)).toBe("");
  expect(formatDateTime("not a date")).toBe("—");
  expect(formatDateTime(null)).toBe("—");
});
