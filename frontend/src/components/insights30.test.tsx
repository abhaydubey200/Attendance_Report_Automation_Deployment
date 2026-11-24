import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import { HO_LEGEND, Person30, Strip30, Trend30, WeekdayHeat, type Pack30 } from "./insights30";

const PACK: Pack30 = {
  labels: ["16-Nov", "17-Nov", "18-Nov"], weekday_of: ["Mon", "Tue", "Wed"], weekdays: ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
  heat_all: [80, 90, null, null, null, null, null],
  trend: [
    { date: "2026-11-15", label: "15-Nov", weekday: "Sun", pct: null, off_day: true, absent: 0, late: 0 },
    { date: "2026-11-16", label: "16-Nov", weekday: "Mon", pct: 80, off_day: false, absent: 5, late: 2 },
    { date: "2026-11-17", label: "17-Nov", weekday: "Tue", pct: 90, off_day: false, absent: 2, late: 1 },
  ],
};

test("trend leaves off days out of the average", () => {
  render(<Trend30 trend={PACK.trend} />);
  expect(screen.getByText(/Average on working days/).textContent).toContain("85%");
  expect(screen.getByText("15-Nov (Sun): off day – left out")).toBeTruthy();
});

test("weekday heatmap hides weekdays with no working days and rows can be clicked", async () => {
  const onClick = vi.fn();
  render(<WeekdayHeat weekdays={PACK.weekdays} rows={[{ name: "Everyone", heat: PACK.heat_all }, { name: "Team A", heat: [70, null, null, null, null, null, null], onClick }]} />);
  expect(screen.getByText("Mon")).toBeTruthy();
  expect(screen.queryByText("Sun")).toBeNull();
  await userEvent.click(screen.getByText("Team A"));
  expect(onClick).toHaveBeenCalled();
});

test("person pop-up shows the strip, facts and closes on Escape", async () => {
  const onClose = vi.fn();
  render(<Person30 title="Asha" facts={[["Attendance", "66.7%"], ["Usual in-time", ""]]} strip="PAO" pack={PACK} legend={HO_LEGEND} onClose={onClose} />);
  expect(screen.getByRole("dialog", { name: "Asha" })).toBeTruthy();
  expect(screen.getByText("66.7%")).toBeTruthy();
  expect(screen.getByTitle("17-Nov Tue: Absent")).toBeTruthy();
  await userEvent.keyboard("{Escape}");
  expect(onClose).toHaveBeenCalled();
});

test("mini strip has one cell per day", () => {
  const { container } = render(<Strip30 strip="PA-" pack={PACK} legend={HO_LEGEND} mini />);
  expect(container.querySelectorAll(".strip30.mini i").length).toBe(3);
});
