import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";
import { App } from "./App";
import { AuthProvider } from "./auth/AuthContext";
import type { AttendanceReport, DayDetail, Employee, EmployeeList, EmployeeReport, Me, ReportDay, Summary, Tally } from "./api/types";

const NAV = [
  { section: "Daily attendance", title: "Upload", slug: "upload", implemented: true, phase: null },
  { section: "Daily attendance", title: "Insights", slug: "insights", implemented: true, phase: null },
  { section: "Daily attendance", title: "Emails", slug: "emails", implemented: true, phase: null },
  { section: "Reports", title: "Attendance report", slug: "reports", implemented: true, phase: null },
  { section: "Reports", title: "Employee report", slug: "employee-report", implemented: true, phase: null },
  { section: "Setup", title: "Employees", slug: "employees", implemented: true, phase: null },
  { section: "Setup", title: "Settings", slug: "settings", implemented: true, phase: null },
];

const OPERATOR: Me = {
  user_id: 0, username: "local.operator", display_name: "APIS HR Operator", roles: ["ADMIN"],
  permissions: ["VIEW_INSIGHTS", "UPLOAD_AND_SEND", "MANAGE_SETTINGS", "MANAGE_EMPLOYEES", "ADMIN_USERS"], departments: [], navigation: NAV,
  environment: "testing", app_name: "APIS Daily Attendance", idle_timeout_minutes: 30, auth_mode: "none",
};
const VIEWER: Me = { ...OPERATOR, username: "viewer", display_name: "Viewer", roles: ["VIEWER"], permissions: ["VIEW_INSIGHTS"],
  navigation: NAV.slice(1, 3), auth_mode: "local" };

const SUMMARY: Summary = {
  employees: 9, tracked: 8, counts: { PRESENT: 3, MISSING_PUNCH: 1, ON_DUTY: 1, HALF_DAY: 1, LEAVE: 1, ABSENT: 1, WEEK_OFF: 0, NOT_TRACKED: 1 },
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
      "HOD:Ravi Kumar": { summary: SUMMARY, highlights: [{ kind: "info", text: "Ravi highlight." }], arrivals: [] },
    },
    hods: [{ name: "Ravi Kumar", scope: "HOD:Ravi Kumar", employees: 2, departments: ["Production"], attendance_pct: 50 }],
    rules: { late_after: "09:30", early_before: "18:00", min_work_hours: 8, long_work_hours: 11, on_duty_codes: ["LD"],
      no_punch_with_shift: "ABSENT", no_punch_no_shift: "NOT_TRACKED", single_punch_counts_present: true, exclude_codes: [] },
  },
  rows: [
    { code: "E1", name: "Asha Synth", category: "Plant", department: "Production", hod: "Ravi Kumar", team: "lead.one", manager: "Mohan", shift: "General Shift", in_time: "09:10", out_time: "18:30", punches: 2, work_minutes: 560,
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

test("report selector switches to a category or an HOD's own people", async () => {
  mockFetch(api(OPERATOR));
  renderApp("/insights");
  await screen.findByText("Attendance 68.8% of 8 tracked employees.");
  await userEvent.selectOptions(screen.getByLabelText("Report for"), "Plant");
  expect(screen.getByText("Plant highlight.")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Excel" })).toHaveAttribute("href", "/api/v1/days/2026-11-13/excel?scope=Plant");
  await userEvent.selectOptions(screen.getByLabelText("Report for"), "HOD:Ravi Kumar");
  expect(screen.getByText("Ravi highlight.")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Excel" })).toHaveAttribute("href", "/api/v1/days/2026-11-13/excel?scope=HOD%3ARavi%20Kumar");
  expect(screen.getByText("Asha Synth")).toBeInTheDocument();
  expect(screen.queryByText("Charu Synth")).not.toBeInTheDocument();
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
  const input = (await screen.findByText(/Drop the Pocket HRMS and.or Bizom file/)).closest(".dropzone")!.querySelector("input")!;
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
      attach_dashboard: true, send_to_hods: true }, smtp_password_set: false, recipients: [], categories: ["Plant", "Sales"], public_url: null });
    if (url.endsWith("/v1/settings/recipients")) return json(200, { count: 1 });
    return json(404, {});
  }));
  renderApp("/settings");
  await userEvent.type(await screen.findByPlaceholderText("name@apisindia.com"), "plant@apisindia.com");
  expect(screen.getByText(/Each HOD automatically gets the report/)).toBeInTheDocument();
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

const EMP = (code: string, name: string, dept: string, hod: string, team: string, status: "ACTIVE" | "LEFT" = "ACTIVE"): Employee => ({
  id: 1, code, name, department: dept, date_of_joining: null, hod_name: hod, hod_email: hod ? `${hod.split(" ")[0].toLowerCase()}@example.com` : "",
  team_lead_email: "", team, reporting_manager: "Mohan", status, exit_date: status === "LEFT" ? "2026-10-31" : null, source: "IMPORT",
  updated_at: null, updated_by: null,
});
const EMPLOYEES: EmployeeList = {
  employees: [EMP("SL1", "Asha Synth", "Production", "Ravi Kumar", "lead.one"), EMP("SL2", "Bimal Synth", "Production", "Ravi Kumar", "Direct to HOD"),
    EMP("HO1", "Charu Synth", "Accounts", "Meena Rao", "Direct to HOD"), EMP("HO2", "Dev Gone", "Accounts", "Meena Rao", "Direct to HOD", "LEFT")],
  summary: { total: 4, active: 3, left: 1, departments: ["Accounts", "Production"], hods_without_email: [],
    hods: [{ name: "Meena Rao", emails: ["meena@example.com"], employees: 1, departments: ["Accounts"] },
      { name: "Ravi Kumar", emails: ["ravi@example.com"], employees: 2, departments: ["Production"] }] },
};

test("employees: HOD card filters, team panel, add employee and mark Left", async () => {
  const spy = mockFetch(api(OPERATOR, (url, init) => {
    if (url.endsWith("/v1/employees") && init?.method === "POST") return json(201, EMP("SL9", "New Person", "Production", "Ravi Kumar", "Direct to HOD"));
    if (url.endsWith("/v1/employees")) return json(200, EMPLOYEES);
    if (url.endsWith("/history")) return json(200, []);
    if (url.endsWith("/v1/employees/SL1/left")) return json(200, EMP("SL1", "Asha Synth", "Production", "Ravi Kumar", "lead.one", "LEFT"));
    return json(404, {});
  }));
  renderApp("/employees");
  await screen.findByText("Charu Synth");
  expect(screen.queryByText("Dev Gone")).not.toBeInTheDocument();            // Left hidden by default
  await userEvent.click(screen.getByRole("button", { name: /Ravi Kumar/ }));
  expect(screen.queryByText("Charu Synth")).not.toBeInTheDocument();
  expect(screen.getByText("Teams under Ravi Kumar")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "lead.one · 1" }));
  expect(screen.queryByText("Bimal Synth")).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Clear all filters" }));
  await userEvent.selectOptions(screen.getByLabelText("Status"), "LEFT");
  expect(screen.getByText("Dev Gone")).toBeInTheDocument();
  await userEvent.selectOptions(screen.getByLabelText("Status"), "ACTIVE");

  await userEvent.click(screen.getByRole("button", { name: "Add employee" }));
  const editor = within(screen.getByText("Add employee", { selector: "h3" }).closest(".card") as HTMLElement);
  await userEvent.type(editor.getByLabelText(/Employee code/), "sl9");
  await userEvent.type(editor.getByLabelText("Employee name"), "New Person");
  await userEvent.type(editor.getByLabelText(/^HODs*Pick/), "Ravi Kumar");
  expect(editor.getByLabelText(/^HOD email/)).toHaveValue("ravi@example.com");     // filled from the HOD
  await userEvent.click(editor.getByRole("button", { name: "Add employee" }));
  expect(await screen.findByText("Employee added.")).toBeInTheDocument();
  const post = spy.mock.calls.find(([u, i]) => String(u).endsWith("/v1/employees") && i?.method === "POST")!;
  expect(JSON.parse(String(post[1]!.body))).toMatchObject({ code: "SL9", name: "New Person", hod_name: "Ravi Kumar", hod_email: "ravi@example.com" });

  await userEvent.click(screen.getAllByRole("button", { name: "Edit" })[0]);
  await userEvent.click(await screen.findByRole("button", { name: "Mark as Left" }));
  expect(await screen.findByText(/marked as Left/)).toBeInTheDocument();
});

test("viewers see employees read-only", async () => {
  mockFetch(api({ ...VIEWER, navigation: NAV.filter((p) => p.slug === "employees") }, (url) =>
    (url.endsWith("/v1/employees") ? json(200, EMPLOYEES) : json(200, []))));
  renderApp("/employees");
  await screen.findByText("Charu Synth");
  expect(screen.queryByRole("button", { name: "Add employee" })).not.toBeInTheDocument();
  expect(screen.queryByText("Import Excel")).not.toBeInTheDocument();
  expect(screen.getAllByRole("button", { name: "View" }).length).toBe(3);
});

const TALLY: Tally = { days: 3, tracked: 3, present: 2, missing_punch: 0, half_day: 0, leave: 0, absent: 1, week_off: 0, not_tracked: 0,
  late: 1, left_early: 0, attendance_pct: 66.7, avg_in_time: "09:40", avg_work_hours: 8.9 };
const RDAY = (date: string, status: ReportDay["status"], label: string, source = "HRMS"): ReportDay => ({
  date, code: "SL1", name: "Asha Synth", category: "Sales", department: "Production", hod: "Ravi Kumar", team: "lead.one", manager: "Mohan",
  status, status_label: label, in_time: status === "PRESENT" ? "09:40" : null, out_time: null, work_hours: null, late_minutes: 0,
  early_minutes: 0, leave_type: null, source, bizom_status: source === "BIZOM" ? "P" : "", flags: [] });
const REPORT: AttendanceReport = {
  from: "2026-10-15", to: "2026-11-13", dates: ["2026-11-12", "2026-11-13"],
  options: { hod: ["Meena Rao", "Ravi Kumar"], department: ["Production"], team: ["lead.one"], manager: ["Mohan"], category: ["Sales"], source: ["BIZOM", "HRMS"] },
  totals: { ...TALLY, employees: 1 },
  employees: [{ code: "SL1", name: "Asha Synth", category: "Sales", department: "Production", hod: "Ravi Kumar", team: "lead.one", manager: "Mohan", ...TALLY }],
  days: [RDAY("2026-11-12", "PRESENT", "Present", "BIZOM"), RDAY("2026-11-13", "ABSENT", "Absent")],
};

test("attendance report: filters go into the link and the Excel download", async () => {
  const spy = mockFetch(api(OPERATOR, (url) => (url.includes("/v1/reports/attendance") ? json(200, REPORT) : json(404, {}))));
  renderApp("/reports");
  await screen.findByText("Asha Synth");
  await userEvent.selectOptions(screen.getByLabelText("HOD"), "Ravi Kumar");
  await waitFor(() => expect(spy.mock.calls.some(([u]) => String(u).includes("hod=Ravi%20Kumar"))).toBe(true));
  expect(screen.getByRole("link", { name: "Download Excel" }).getAttribute("href")).toContain("hod=Ravi%20Kumar");
  await userEvent.click(screen.getByRole("button", { name: "Day by day" }));
  expect(await screen.findByText("Day by day", { selector: "h3" })).toBeInTheDocument();
  expect(screen.getAllByText("Bizom").length).toBeGreaterThan(1);   // source column + Source filter option
  expect(screen.getAllByRole("link", { name: "Asha Synth" })[0]).toHaveAttribute("href", expect.stringContaining("/employee-report?code=SL1"));
});

test("employee report shows each day with its source", async () => {
  const body: EmployeeReport = { employee: { code: "SL1", name: "Asha Synth", department: "Production", hod_name: "Ravi Kumar", team: "lead.one",
    reporting_manager: "Mohan", status: "ACTIVE" }, in_master: true, from: "2026-10-15", to: "2026-11-13", summary: TALLY,
    days: [RDAY("2026-11-12", "PRESENT", "Present", "BIZOM"), RDAY("2026-11-13", "ABSENT", "Absent")] };
  mockFetch(api(OPERATOR, (url) => {
    if (url.includes("/v1/reports/employee/SL1")) return json(200, body);
    if (url.endsWith("/v1/employees")) return json(200, EMPLOYEES);
    return json(404, {});
  }));
  renderApp("/employee-report?code=SL1");
  expect(await screen.findByText("Asha Synth (SL1)")).toBeInTheDocument();
  expect(screen.getByText("66.7%")).toBeInTheDocument();
  expect(screen.getAllByText("Absent").length).toBeGreaterThan(0);
  expect(screen.getByRole("link", { name: "Download Excel" })).toHaveAttribute("href", "/api/v1/reports/employee/SL1/excel?from=2026-10-15&to=2026-11-13");
});
