import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";
import { App } from "./App";
import { AuthProvider } from "./auth/AuthContext";
import type { Me } from "./api/types";

const ME: Me = {
  user_id: 1,
  username: "hod.sales",
  display_name: "Test HOD",
  roles: ["HOD"],
  permissions: ["DASHBOARD_VIEW", "REPORT_VIEW_HOD"],
  departments: ["SALES"],
  navigation: [
    { section: "Overview", title: "Executive Dashboard", slug: "dashboard", implemented: true, phase: null },
    { section: "MIS Reports", title: "HOD Reports", slug: "hod-reports", implemented: false, phase: 8 },
  ],
  environment: "testing",
  app_name: "APIS Intelligent HR & Attendance MIS",
  idle_timeout_minutes: 30,
  auth_mode: "local",
};

const OPERATOR: Me = {
  ...ME,
  user_id: 0,
  username: "local.operator",
  display_name: "APIS HR Operator",
  roles: ["HR_ADMIN", "SYSTEM_ADMIN"],
  auth_mode: "none",
};

const SUMMARY = {
  today_ist: "2026-11-14",
  reporting_date: null,
  last_successful_run: null,
  latest_run_status: null,
  uploaded_dataset_count: 0,
  rule_version: "0.0.0-draft",
  rule_approval_status: "NOT_APPROVED",
  rules_approved: false,
  kpis: [{ key: "present", label: "Present", value: null, status: "NO_DATA" }],
  message: "No processed attendance data yet.",
};

function json(status: number, body: unknown) {
  return Promise.resolve(new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }));
}

type Handler = (url: string, init?: RequestInit) => Promise<Response>;

function mockFetch(handler: Handler) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(((input: RequestInfo | URL, init?: RequestInit) =>
    handler(String(input), init)) as typeof fetch);
}

function renderApp(path = "/") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </MemoryRouter>,
  );
}

test("sign-in mode: shows the login screen when there is no session", async () => {
  mockFetch(() => json(401, { detail: "Not authenticated" }));
  renderApp();
  expect(await screen.findByRole("button", { name: "Sign in" })).toBeInTheDocument();
  expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
});

test("failed login shows the server's generic message", async () => {
  mockFetch((url) =>
    url.endsWith("/auth/login")
      ? json(401, { detail: "Invalid username or password, or the account is locked." })
      : json(401, { detail: "Not authenticated" }),
  );
  renderApp();
  await userEvent.type(await screen.findByLabelText("Username"), "x");
  await userEvent.type(screen.getByLabelText("Password"), "y");
  await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Invalid username or password");
  expect(screen.getByLabelText("Password")).toHaveValue("");
});

test("successful login renders permitted navigation and the dashboard", async () => {
  const fetchSpy = mockFetch((url) => {
    if (url.endsWith("/auth/login")) return json(200, ME);
    if (url.endsWith("/dashboard/summary")) return json(200, SUMMARY);
    return json(401, { detail: "Not authenticated" });
  });
  renderApp();
  await userEvent.type(await screen.findByLabelText("Username"), "hod.sales");
  await userEvent.type(screen.getByLabelText("Password"), "secret");
  await userEvent.click(screen.getByRole("button", { name: "Sign in" }));

  expect(await screen.findByRole("heading", { name: "Executive Dashboard" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /HOD Reports/ })).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: /Users and Roles/ })).not.toBeInTheDocument();
  expect(await screen.findByText("NOT APPROVED")).toBeInTheDocument();
  expect(screen.getByText("Today: 14-Nov-2026 (IST)")).toBeInTheDocument();

  // CSRF header and cookie credentials on the login call.
  const [, init] = fetchSpy.mock.calls.find(([u]) => String(u).endsWith("/auth/login"))!;
  expect((init!.headers as Record<string, string>)["X-APIS-Request"]).toBe("1");
  expect(init!.credentials).toBe("include");
});

test("pages not granted by the API are not routable", async () => {
  mockFetch((url) => (url.endsWith("/auth/me") ? json(200, ME) : json(200, SUMMARY)));
  renderApp("/users");
  expect(await screen.findByRole("heading", { name: "Page not available" })).toBeInTheDocument();
});

test("HOD reports list only what the API returns, with provisional marking and download links", async () => {
  const reports = [{
    report_id: 7, run_id: 1, run_ref: "RUN-20261113-v1", reporting_date: "2026-11-13", report_type: "HOD",
    department_code: "SALES", file_format: "XLSX", report_version: 1, provisional: true, status: "GENERATED",
    generated_by: "system", generated_at: "2026-11-14T03:00:00Z",
  }];
  mockFetch((url) => (url.endsWith("/auth/me") ? json(200, ME) : url.includes("/v1/reports") ? json(200, reports) : json(200, SUMMARY)));
  renderApp("/hod-reports");
  expect(await screen.findByText("PROVISIONAL")).toBeInTheDocument();
  expect(screen.getByText(/SALES/)).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Download" })).toHaveAttribute("href", "/api/v1/reports/7/download");
  expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();   // HOD lacks REPORT_APPROVE
});

test("analyst shows the answer with its source and period", async () => {
  const meAi = { ...ME, permissions: [...ME.permissions, "AI_USE"],
    navigation: [...ME.navigation, { section: "AI Intelligence", title: "Attendance Analyst", slug: "ai-analyst", implemented: true, phase: null }] };
  mockFetch((url, init) => {
    if (url.endsWith("/auth/me")) return json(200, meAi);
    if (url.endsWith("/v1/ai/ask")) {
      expect(JSON.parse(String(init?.body)).question).toContain("absenteeism");
      return json(200, { text: "On 13-Nov-2026, FIN recorded the most absences (1 of 2).", table: null, intent: "DEPARTMENT_HIGHEST_ABSENT",
        source: "Processing run RUN-20261113-v1 (rule version 0.0.0-draft, provisional)", period: "2026-11-13", supported_questions: [] });
    }
    return json(200, SUMMARY);
  });
  renderApp("/ai-analyst");
  await userEvent.type(await screen.findByRole("textbox"), "Which department had the highest absenteeism?");
  await userEvent.click(screen.getByRole("button", { name: "Ask" }));
  expect(await screen.findByText(/FIN recorded the most absences/)).toBeInTheDocument();
  expect(screen.getByText(/RUN-20261113-v1/)).toBeInTheDocument();
});

test("sign-in mode: a 401 during use returns to the login screen with a notice", async () => {
  mockFetch((url) => (url.endsWith("/auth/me") ? json(200, ME) : json(401, { detail: "Not authenticated" })));
  renderApp("/dashboard");
  await waitFor(() => expect(screen.getByRole("button", { name: "Sign in" })).toBeInTheDocument());
  expect(screen.getByText(/session has ended/)).toBeInTheDocument();
});

test("no-login mode: opens straight on the dashboard with no sign-in or sign-out", async () => {
  const fetchSpy = mockFetch((url) => (url.endsWith("/auth/me") ? json(200, OPERATOR) : json(200, SUMMARY)));
  renderApp();
  expect(await screen.findByRole("heading", { name: "Executive Dashboard" })).toBeInTheDocument();
  expect(screen.getByText("APIS HR Operator")).toBeInTheDocument();
  expect(screen.getByRole("img", { name: "APIS India Limited" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Sign (in|out)/ })).not.toBeInTheDocument();
  expect(screen.getByText(/no sign-in/)).toBeInTheDocument();
  expect(fetchSpy.mock.calls.some(([u]) => String(u).endsWith("/auth/login"))).toBe(false);
});

test("server unreachable shows a retry screen, not a login form", async () => {
  vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("Failed to fetch"));
  renderApp();
  expect(await screen.findByText(/not reachable/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  expect(screen.queryByLabelText("Password")).not.toBeInTheDocument();
});
