import { formatDate, formatDateTime } from "./format";

test("formats calendar dates without timezone drift", () => {
  expect(formatDate("2026-11-13")).toBe("13-Nov-2026");
  expect(formatDate("2026-01-01")).toBe("01-Jan-2026");
  expect(formatDate(null)).toBe("—");
});

test("formats UTC instants in IST", () => {
  expect(formatDateTime("2026-11-13T20:00:00Z")).toBe("14-Nov-2026 01:30 IST");
  expect(formatDateTime("not a date")).toBe("—");
  expect(formatDateTime(null)).toBe("—");
});
