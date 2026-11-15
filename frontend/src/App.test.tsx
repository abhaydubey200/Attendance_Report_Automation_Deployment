import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";
import { App } from "./App";
import { AuthProvider } from "./auth/AuthContext";
import type { DayDetail, Me, Summary } from "./api/types";

const NAV = [
  { section: "Daily attendance", title: "Upload", slug: "upload", implemented: true, phase: null },
  { section: "Daily attendance", title: "Insights", slug: "insights", implemented: true, phase: null },
  { section: "Daily attendance", title: "Emails", slug: "emails", implemented: true, phase: null },
  { section: "Setup", title: "Settings", slug: "settings", implemented: true, phase: null },
];

const OPERATOR: Me = {
  user_id: 0, username: "local.operator", display_name: "APIS HR Operator", roles: ["ADMIN"],
  permissions: ["VIEW_INSIGHTS", "UPLOAD_AND_SEND", "MANAGE_SETTINGS", "ADMIN_USERS"], departments: [], navigation: NAV,
  environment: "testing", app_name: "APIS Daily Attendance", idle_timeout_minutes: 30, auth_mode: "none",
};
const VIEWER: Me = { ...OPERATOR, username: "viewer", display_name: "Viewer", roles: ["VIEWER"], permissions: ["VIEW_INSIGHTS"],
  navigation: NAV.slice(1, 3), auth_mode: "local" };

const SUMMARY: Summary = {
  employees: 9, tracked: 8, counts: { PRESENT: 3, MISSING_PUNCH: 1, ON_DUTY: 1, HALF_DAY: 1, LEAVE: 1, ABSENT: 1, NOT_TRACKED: 1 },
  attendance_pct: 68.8, absent_pct: 12.5, late: 1, late_pct: 25, avg_late_minutes: 45, left_early: 1, short_hours: 1, long_hours: 0,
  avg_in_time: "09:35", earliest_in: "09:00", latest_in: "10:15", avg_work_hours: 8.5,
};
const DAY: DayDetail = {
  upload_id: 1, report_date: "2026-11-13", file: "AttendanceSummary.xlsx", uploaded_by: "local.operator", uploaded_at: "2026-11-14T04:00:00Z",
  employees: 9, emails: [],
  insights: {
    report_date: "2026-11-13", excluded: 1, categories: ["Plant", "Sales"], previous_date: null,
    by_category: { Plant: SUMMARY, Sales: SUMMARY },
    scopes: {
      ALL: { summary: SUMMARY, highlights: [{ kind: "warn", text: "Attendance 68.8% of 8 tracked employees." }], arrivals: [{ label: "09:00-09:30", count: 3 }] },
      Plant: { summary: SUMMARY, highlights: [{ kind: "info", text: "Plant highlight." }], arrivals: [] },
      Sales: { summary: SUMMARY, highlights: [], arrivals: [] },
    },
    rules: { late_after: "09:30", early_before: "18:00", min_work_hours: 8, long_work_hours: 11, on_duty_codes: ["LD"],
      no_punch_with_shift: "ABSENT", no_punch_no_shift: "NOT_TRACKED", single_punch_counts_present: true, exclude_codes: [] },
  },
  rows: [
    { code: "E1", name: "Asha Synth", category: "Plant", shift: "General Shift", in_time: "09:10", out_time: "18:30", punches: 2, work_minutes: 560,
      work_hours: 9.33, leave_type: null, day_portion: null, status: "PRESENT", status_label: "Present", late_minutes: 0, early_minutes: 0, flags: [] },
    { code: "E5", name: "Bimal Synth", category: "Plant", shift: "General Shift", in_time: null, out_time: null, punches: 0, work_minutes: null,
      work_hours: null, leave_type: null, day_portion: null, status: "ABSENT", status_label: "Absent", late_minutes: 0, early_minutes: 0, flags: [] },
    { code: "E2", name: "Charu Synth", category: "Sales", shift: "General Shift", in_time: "10:15", out_time: "19:00", punches: 2, work_minutes: 525,
      work_hours: 8.75, leave_type: null, day_portion: null, status: "PRESENT", status_label: "Present", late_minutes: 45, early_minutes: 0, flags: ["LATE"] },
  ],
};
const DAYS = [{ report_date: "2026-11-13", employees: 9, attendance_pct: 68.8, absent: 1, late: 1, emails: 0, email_failed: 0, uploaded_at: "2026-11-14T04:00:00Z" }];

function json(status: number, body: unknown) {
  return Promise.resolve(new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }));
}

type Handler = (url: string, init?: RequestInit) => Promise<Response>;
function mockFetch(handler: Handler) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(((input: RequestInfo | URL, init?: RequestInit) => handler(String(input), init)) as typeof fetch);
}

function renderApp(path = "/") {
  return render(<MemoryRouter initialEntries={[path]}><AuthProvider><App /></AuthProvider></MemoryRouter>);
}

const api = (me: Me, extra: Handler = () => json(404, { detail: "nope" })): Handler => (url, init) => {
  if (url.endsWith("/auth/me")) return json(200, me);
  if (url.endsWith("/v1/days")) return json(200, DAYS);
  if (url.endsWith("/v1/days/2026-11-13")) return json(200, DAY);
  return extra(url, init);
};

test("no-login mode opens on Insights with KPIs, highlights and downloads", async () => {
  mockFetch(api(OPERATOR));
  renderApp();
  expect(await screen.findByText("Attendance 68.8% of 8 tracked employees.")).toBeInTheDocument();
  expect(screen.getAllByText("68.8%").length).toBeGreaterThan(0);
  expect(screen.getByRole("link", { name: "Excel" })).toHaveAttribute("href", "/api/v1/days/2026-11-13/excel?scope=ALL");
  expect(screen.getByRole("link", { name: "HTML dashboard" })).toHaveAttribute("href", "/api/v1/days/2026-11-13/dashboard?scope=ALL");
  expect(screen.queryByRole("button", { name: /Sign (in|out)/ })).not.toBeInTheDocument();
});

test("employee table filters by status chip and search", async () => {
  mockFetch(api(OPERATOR));
  renderApp("/insights");
  expect(await screen.findByText("Asha Synth")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Late" }));
  expect(screen.queryByText("Asha Synth")).not.toBeInTheDocument();
  expect(screen.getByText("Charu Synth")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "All" }));
  await userEvent.type(screen.getByLabelText("Search employees"), "bimal");
  expect(screen.getByText("Bimal Synth")).toBeInTheDocument();
  expect(screen.queryByText("Charu Synth")).not.toBeInTheDocument();
});

test("team selector switches the highlights and the download scope", async () => {
  mockFetch(api(OPERATOR));
  renderApp("/insights");
  await screen.findByText("Attendance 68.8% of 8 tracked employees.");
  await userEvent.selectOptions(screen.getByLabelText("Team"), "Plant");
  expect(screen.getByText("Plant highlight.")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Excel" })).toHaveAttribute("href", "/api/v1/days/2026-11-13/excel?scope=Plant");
});

test("viewers do not see upload, settings or the send button", async () => {
  mockFetch(api(VIEWER));
  renderApp("/insights");
  await screen.findByText("Attendance 68.8% of 8 tracked employees.");
  expect(screen.queryByRole("button", { name: "Send emails" })).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "Settings" })).not.toBeInTheDocument();
});

test("upload shows the result and offers Replace when the day exists", async () => {
  let calls = 0;
  const spy = mockFetch(api(OPERATOR, (url, init) => {
    if (url.endsWith("/v1/days/upload")) {
      calls += 1;
      const replace = (init?.body as FormData).get("replace");
      if (replace === "false") return json(409, { detail: "13-Nov-2026 is already uploaded. Upload again with 'Replace' to use this file instead." });
      return json(200, { ...DAY, auto_sent: true, email_results: [
        { scope: "ALL", scope_label: "All employees", recipients: ["hr@example.com"], status: "SAVED", detail: null },
        { scope: "Sales", scope_label: "Sales", recipients: [], status: "NO_RECIPIENTS", detail: "Add a recipient for this in Settings." }] });
    }
    return json(404, {});
  }));
  renderApp("/upload");
  const file = new File(["x"], "AttendanceSummary.xlsx");
  const input = (await screen.findByText(/Drop the Attendance Summary file/)).closest(".dropzone")!.querySelector("input")!;
  await userEvent.upload(input, file);
  await userEvent.click(await screen.findByRole("button", { name: "Replace and send again" }));
  expect(await screen.findByText(/13-Nov-2026 processed: 9 employees/)).toBeInTheDocument();
  const emails = screen.getByRole("heading", { name: "Emails" }).closest(".card")!;
  expect(within(emails as HTMLElement).getByText("hr@example.com")).toBeInTheDocument();
  expect(calls).toBe(2);
  const uploadCall = spy.mock.calls.find(([u]) => String(u).endsWith("/v1/days/upload"))!;
  expect((uploadCall[1]!.headers as Record<string, string>)["X-APIS-Request"]).toBe("1");
});

test("settings saves recipients as one list", async () => {
  const spy = mockFetch(api(OPERATOR, (url) => {
    if (url.endsWith("/v1/settings")) return json(200, { rules: DAY.insights.rules, email: { mode: "test", auto_send: true, sender: null,
      smtp_host: null, smtp_port: 587, smtp_starttls: true, smtp_username: null, subject_prefix: "APIS Daily Attendance", attach_excel: true,
      attach_dashboard: true }, smtp_password_set: false, recipients: [], categories: ["Plant", "Sales"], public_url: null });
    if (url.endsWith("/v1/settings/recipients")) return json(200, { count: 1 });
    return json(404, {});
  }));
  renderApp("/settings");
  await userEvent.type(await screen.findByPlaceholderText("name@apisindia.com"), "plant@apisindia.com");
  expect(screen.getByText(/No manager yet for: Plant, Sales/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Save recipients" }));
  expect(await screen.findByText("Recipients saved.")).toBeInTheDocument();
  const put = spy.mock.calls.find(([u, i]) => String(u).endsWith("/v1/settings/recipients") && i?.method === "PUT")!;
  expect(JSON.parse(String(put[1]!.body)).recipients[0].email).toBe("plant@apisindia.com");
});

test("sign-in mode shows the login screen, and a failed login keeps the message", async () => {
  mockFetch((url) => (url.endsWith("/auth/login") ? json(401, { detail: "Invalid username or password, or the account is locked." })
    : json(401, { detail: "Not authenticated" })));
  renderApp();
  await userEvent.type(await screen.findByLabelText("Username"), "x");
  await userEvent.type(screen.getByLabelText("Password"), "y");
  await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Invalid username or password");
});

test("pages the API does not list are not routable", async () => {
  mockFetch(api(VIEWER));
  renderApp("/settings");
  expect(await screen.findByRole("heading", { name: "Page not available" })).toBeInTheDocument();
});

test("server unreachable shows a retry screen", async () => {
  vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("Failed to fetch"));
  renderApp();
  await waitFor(() => expect(screen.getByText(/not reachable/)).toBeInTheDocument());
});
