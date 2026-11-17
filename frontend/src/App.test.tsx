import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";
import { FeedbackProvider } from "./components/feedback";
import { App } from "./App";
import { AuthProvider } from "./auth/AuthContext";
import type { AttendanceReport, DayDetail, DayMail, Employee, EmployeeList, EmployeeReport, MailItem, Me, ReportDay, Summary, Tally } from "./api/types";

const MAIL_ITEM = (key: string, name: string, status: MailItem["status"], extra: Partial<MailItem> = {}): MailItem => ({
  id: key.length, report_date: "2026-11-13", key, name, role: key === "DIRECTOR" ? "Director" : "Team lead", to: key.includes("@") ? key : "",
  cc: "", subject: `Daily Attendance | 13-Nov-2026 | ${name}`, status,
  sendable: ["PENDING", "FAILED", "TEST_SENT"].includes(status), note: null, attempts: 0, team: 2, summary: 0, company: 0,
  exceptions: 0, attention: 1, counts: { team: { total: 2, present: 1, absent: 1, leave: 0, od: 0, wfh: 0, late: 0, missing_punch: 0,
    week_off: 0, not_tracked: 0, no_record: 0, attendance_pct: 50, attention: 1 }, summary: null, company: null, exceptions: 0 },
  sent_at: null, approved_by: null, ...extra });

const NAV = [
  { section: "Daily attendance", title: "Upload", slug: "upload", implemented: true, phase: null },
  { section: "Daily attendance", title: "Insights", slug: "insights", implemented: true, phase: null },
  { section: "Daily attendance", title: "Approve emails", slug: "mail", implemented: true, phase: null },
  { section: "Daily attendance", title: "Email log", slug: "emails", implemented: true, phase: null },
  { section: "Reports", title: "Attendance report", slug: "reports", implemented: true, phase: null },
  { section: "Reports", title: "Employee report", slug: "employee-report", implemented: true, phase: null },
  { section: "Setup", title: "Employees", slug: "employees", implemented: true, phase: null },
  { section: "Setup", title: "Automation", slug: "automation", implemented: true, phase: null },
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
  employees: 9, tracked: 8, counts: { PRESENT: 3, MISSING_PUNCH: 1, ON_DUTY: 1, HALF_DAY: 1, LEAVE: 1, ABSENT: 1, WEEK_OFF: 0, HOLIDAY: 0, WFH: 0, NOT_TRACKED: 1 },
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
    rules: { late_after: "09:30", early_before: "19:30", min_work_hours: 8, long_work_hours: 11, on_duty_codes: ["LD"],
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
  return render(<MemoryRouter initialEntries={[path]}><AuthProvider><FeedbackProvider><App /></FeedbackProvider></AuthProvider></MemoryRouter>);
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

test("upload: three dataset boxes, manual mode by default, Replace when the day exists", async () => {
  let calls = 0;
  const spy = mockFetch(api(OPERATOR, (url, init) => {
    if (url.endsWith("/v1/upload/options")) return json(200, { default_mode: "manual", wait_for_permission: true, mode: "test", can_import_master: true, employees: 729 });
    if (url.endsWith("/v1/days/upload")) {
      calls += 1;
      const replace = (init?.body as FormData).get("replace");
      if (replace === "false") return json(409, { detail: "Pocket HRMS file for 13-Nov-2026 is already uploaded. Upload again with 'Replace' to use this file instead." });
      return json(200, { ...DAY, permission_file: "PermissionReportAdmin.xlsx", auto_sent: false, send_mode: "manual",
        send_note: "2 email(s) ready - review and approve them on the Approve emails screen.",
        mail: [MAIL_ITEM("lead.a@example.com", "Lead A", "PENDING"), MAIL_ITEM("DIRECTOR", "Director", "PENDING")] });
    }
    return json(404, {});
  }));
  renderApp("/upload");
  expect(await screen.findByLabelText(/Manual/)).toBeChecked();
  expect(screen.getByRole("button", { name: "Upload" })).toBeDisabled();
  await userEvent.upload(screen.getByLabelText("Attendance Summary file"), new File(["x"], "AttendanceSummary.xlsx"));
  await userEvent.upload(screen.getByLabelText("Permission Report file"), new File(["y"], "PermissionReportAdmin.xlsx"));
  expect(screen.getByText("AttendanceSummary.xlsx")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Upload" }));
  await userEvent.click(await screen.findByRole("button", { name: "Replace with these files" }));
  expect(await screen.findByText(/13-Nov-2026 processed: 9 employees/)).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Review and approve 2 email(s) →" })).toHaveAttribute("href", "/mail?date=2026-11-13");
  expect(calls).toBe(2);
  const uploadCall = spy.mock.calls.filter(([u]) => String(u).endsWith("/v1/days/upload")).pop()!;
  const form = uploadCall[1]!.body as FormData;
  expect((form.get("hrms") as File).name).toBe("AttendanceSummary.xlsx");
  expect((form.get("permission") as File).name).toBe("PermissionReportAdmin.xlsx");
  expect(form.get("master")).toBeNull();
  expect(form.get("send_mode")).toBe("manual");
  expect((uploadCall[1]!.headers as Record<string, string>)["X-APIS-Request"]).toBe("1");
});

test("upload: auto mode sends at once and master-only upload just updates the employees", async () => {
  const spy = mockFetch(api(OPERATOR, (url, init) => {
    if (url.endsWith("/v1/upload/options")) return json(200, { default_mode: "manual", wait_for_permission: false, mode: "test", can_import_master: true, employees: 0 });
    if (url.endsWith("/v1/days/upload")) {
      const form = init!.body as FormData;
      if (!form.get("hrms")) return json(200, { report_date: null, mail: [], auto_sent: false, send_note: "Employee master updated. Upload the attendance files to prepare the emails.",
        master_import: { rows: 729, added: 729, updated: 0, unchanged: 0, kept_left: 0, not_in_file: 0, problems: [], problem_count: 0,
          routing: { coverage: { checked: 729, differences: 0, examples: [] } } } });
      return json(200, { ...DAY, auto_sent: true, send_mode: "auto", send_note: null, mail: [MAIL_ITEM("lead.a@example.com", "Lead A", "SAVED")] });
    }
    return json(404, {});
  }));
  renderApp("/upload");
  await userEvent.upload(await screen.findByLabelText("Employee master file"), new File(["m"], "APIS_Email_Routing_Master.xlsx"));
  await userEvent.click(screen.getByRole("button", { name: "Upload" }));
  expect(await screen.findByText(/729 added/)).toBeInTheDocument();
  expect(screen.getByText(/matches the coverage sheet/)).toBeInTheDocument();
  await userEvent.click(screen.getByLabelText(/Auto/));
  await userEvent.upload(screen.getByLabelText("Attendance Summary file"), new File(["x"], "AttendanceSummary.xlsx"));
  await userEvent.click(screen.getByRole("button", { name: "Upload and send emails" }));
  expect(await screen.findByText(/Auto: 1 email\(s\) saved to the outbox/)).toBeInTheDocument();
  const last = spy.mock.calls.filter(([u]) => String(u).endsWith("/v1/days/upload")).pop()!;
  expect((last[1]!.body as FormData).get("send_mode")).toBe("auto");
});

test("settings: Director and HR mailboxes are saved as lists with the routing switches", async () => {
  const email = { mode: "test", approval_required: true, auto_send: true, wait_for_permission: true, sender: null, reply_to: null,
    subject_prefix: "Daily Attendance", attach_excel: true,
    attach_dashboard: true, retry_attempts: 3, team_emails: true, hod_summary: true, director_report: true, hr_exceptions: true,
    hod_cc_on_team: false, hr_cc_on_hod_summary: false, test_recipient: null, test_cc: [], director_name: "Director", director_emails: [], hr_emails: [] };
  const spy = mockFetch(api(OPERATOR, (url) => {
    if (url.endsWith("/v1/settings")) return json(200, { rules: DAY.insights.rules, email, secrets: { GMAIL_CLIENT_ID: true, GMAIL_CLIENT_SECRET: true, GMAIL_REFRESH_TOKEN: false }, categories: [], public_url: null });
    if (url.endsWith("/v1/settings/email")) return json(200, email);
    return json(404, {});
  }));
  renderApp("/settings");
  await userEvent.type(await screen.findByPlaceholderText("director@apisindia.com"), "md@example.com, cfo@example.com");
  await userEvent.type(screen.getByPlaceholderText("hr.attendance@apisindia.com"), "hr@example.com");
  await userEvent.click(screen.getByLabelText(/CC the HOD on team-lead emails/));
  expect(screen.getByText(/GMAIL_REFRESH_TOKEN ✗ not set/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Save email settings" }));
  expect(await screen.findByText("Email settings saved.")).toBeInTheDocument();
  const put = spy.mock.calls.find(([u, i]) => String(u).endsWith("/v1/settings/email") && i?.method === "PUT")!;
  const body = JSON.parse(String(put[1]!.body));
  expect(body.director_emails).toEqual(["md@example.com", "cfo@example.com"]);
  expect(body.hr_emails).toEqual(["hr@example.com"]);
  expect(body.hod_cc_on_team).toBe(true);
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
  updated_at: null, updated_by: null, routing_issue: "",
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
const RDAY = (date: string, status: ReportDay["status"], label: string, permission?: string): ReportDay => ({
  date, code: "SL1", name: "Asha Synth", category: "Sales", department: "Production", hod: "Ravi Kumar", team: "lead.one", manager: "Mohan",
  status, status_label: label, in_time: status === "PRESENT" ? "09:40" : null, out_time: null, work_hours: null, late_minutes: 0,
  early_minutes: 0, leave_type: null, source: "HRMS", permission: permission ?? "", flags: [] });
const REPORT: AttendanceReport = {
  from: "2026-10-15", to: "2026-11-13", dates: ["2026-11-12", "2026-11-13"],
  options: { hod: ["Meena Rao", "Ravi Kumar"], department: ["Production"], team: ["lead.one"], manager: ["Mohan"], category: ["Sales"], source: ["HRMS"] },
  totals: { ...TALLY, employees: 1 },
  employees: [{ code: "SL1", name: "Asha Synth", category: "Sales", department: "Production", hod: "Ravi Kumar", team: "lead.one", manager: "Mohan", ...TALLY }],
  days: [RDAY("2026-11-12", "PRESENT", "Present", "Approved 09:30-11:30"), RDAY("2026-11-13", "ABSENT", "Absent")],
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
  expect(screen.getByText("Approved 09:30-11:30")).toBeInTheDocument();   // Permission column
  expect(screen.getAllByRole("link", { name: "Asha Synth" })[0]).toHaveAttribute("href", expect.stringContaining("/employee-report?code=SL1"));
});

test("employee report shows each day with its source", async () => {
  const body: EmployeeReport = { employee: { code: "SL1", name: "Asha Synth", department: "Production", hod_name: "Ravi Kumar", team: "lead.one",
    reporting_manager: "Mohan", status: "ACTIVE" }, in_master: true, from: "2026-10-15", to: "2026-11-13", summary: TALLY,
    days: [RDAY("2026-11-12", "PRESENT", "Present", "Approved 09:30-11:30"), RDAY("2026-11-13", "ABSENT", "Absent")] };
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

test("approve emails: preview mode lists every recipient and approves all or selected", async () => {
  let items = [MAIL_ITEM("lead.a@example.com", "Lead A", "PENDING"), MAIL_ITEM("rahul@example.com", "Rahul Sharma", "PENDING"),
    MAIL_ITEM("DIRECTOR", "Director", "HELD", { note: "Director email not set (Settings -> Email)." })];
  const dayMail = (): DayMail => ({ report_date: "2026-11-13", mode: "test", approval_required: true, test_recipient: null, items,
    status: items.reduce((acc, i) => ({ ...acc, [i.status]: (acc[i.status] ?? 0) + 1 }), {} as DayMail["status"]), planned: true });
  const spy = mockFetch(api(OPERATOR, (url, init) => {
    if (url.endsWith("/mail/approve")) {
      const ids: number[] | null = JSON.parse(String(init!.body)).ids;
      items = items.map((i) => (i.status === "PENDING" && (!ids || ids.includes(i.id)) ? { ...i, status: "SAVED", sendable: false } : i));
      return json(200, { ...dayMail(), sent_now: ids ? ids.length : 2 });
    }
    if (url.endsWith("/v1/days/2026-11-13/mail")) return json(200, dayMail());
    return json(404, {});
  }));
  renderApp("/mail");
  expect(await screen.findByText("Lead A")).toBeInTheDocument();
  expect(screen.getByText("Director email not set (Settings -> Email).")).toBeInTheDocument();
  await userEvent.click(screen.getByLabelText("Select Rahul Sharma"));
  await userEvent.click(screen.getByRole("button", { name: "Approve selected (1)" }));
  expect(await screen.findByText(/1 of 1 email\(s\) saved to the outbox/)).toBeInTheDocument();
  const first = spy.mock.calls.find(([u]) => String(u).endsWith("/mail/approve"))!;
  expect(JSON.parse(String(first[1]!.body)).ids).toEqual([MAIL_ITEM("rahul@example.com", "", "PENDING").id]);
  await userEvent.click(await screen.findByRole("button", { name: "Approve & send all (1)" }));
  await waitFor(() => expect(screen.getAllByText("Saved (test mode)").length).toBe(2));
  await userEvent.click(screen.getAllByRole("button", { name: "Preview" })[0]);
  expect(screen.getByTitle("Email preview")).toHaveAttribute("src", expect.stringContaining("/preview"));
});

test("automation: job history, run the daily job, month-end list", async () => {
  const runs = [{ id: 2, job: "DAILY", target: "2026-11-13", trigger: "SCHEDULED", status: "PARTIAL", started_by: "scheduler",
    summary: { employees: 717, processed: ["a.xlsx"], emails: { SENT: 29, FAILED: 2 }, send_mode: "auto" }, error: null,
    started_at: "2026-11-14T04:00:00Z", finished_at: "2026-11-14T04:01:30Z", seconds: 90 }];
  const spy = mockFetch(api(OPERATOR, (url) => {
    if (url.endsWith("/v1/jobs")) return json(200, { runs, inbox: "D:\inbox", yesterday: "2026-11-13", keep_months: 2, backup_keep_days: 30,
      database: "sqlite", previous_month: "2026-10" });
    if (url.endsWith("/v1/jobs/daily")) return json(200, { status: "SUCCESS" });
    if (url.endsWith("/v1/monthly")) return json(200, [{ month: "2026-10", label: "Oct-2026", days: 26, employees: 717, attendance_pct: "81.5",
      status: "ARCHIVED", archive: true, generated_at: "2026-11-01T05:00:00Z", generated_by: "scheduler", cleaned_at: null }]);
    return json(404, {});
  }));
  renderApp("/automation");
  expect(await screen.findByText(/717 employees · 1 new file\(s\) · 29 sent, 2 failed/)).toBeInTheDocument();
  expect(screen.getByText("Oct-2026")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Run daily job" }));
  expect(await screen.findByText("Daily job: success")).toBeInTheDocument();
  const call = spy.mock.calls.find(([u]) => String(u).endsWith("/v1/jobs/daily"))!;
  expect(JSON.parse(String(call[1]!.body))).toEqual({ report_date: "2026-11-13", send_mode: "manual" });
});
