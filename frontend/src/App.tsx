import type { ComponentType } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "./auth/AuthContext";
import { Layout } from "./components/Layout";
import { Loading, Notice, PageHeader } from "./components/ui";
import { AutomationPage } from "./pages/AutomationPage";
import { DatabasePage } from "./pages/DatabasePage";
import { EmailsPage } from "./pages/EmailsPage";
import { MailPage } from "./pages/MailPage";
import { EmployeesPage } from "./pages/EmployeesPage";
import { EmployeeReportPage, ReportsPage } from "./pages/ReportsPage";
import { HomePage } from "./pages/HomePage";
import { InsightsPage } from "./pages/InsightsPage";
import { LoginPage, UnavailablePage } from "./pages/LoginPage";
import { ModulesPage } from "./pages/ModulesPage";
import { SalesHomePage } from "./pages/SalesHomePage";
import { SettingsPage } from "./pages/SettingsPage";
import { UploadPage } from "./pages/UploadPage";

// Routes exist only for screens the API lists for this user; the API checks permissions on every call.
const SCREENS: Record<string, ComponentType> = {
  home: HomePage,
  upload: UploadPage,
  insights: InsightsPage,
  mail: MailPage,
  emails: EmailsPage,
  employees: EmployeesPage,
  automation: AutomationPage,
  reports: ReportsPage,
  "employee-report": EmployeeReportPage,
  settings: SettingsPage,
  database: DatabasePage,
};

function NotFoundPage() {
  return (
    <>
      <PageHeader title="Page not available" />
      <Notice kind="warn">This page does not exist or you do not have access to it.</Notice>
    </>
  );
}

export function App() {
  const { me, loading, needsSignIn, unavailable } = useAuth();

  if (loading) {
    return (
      <div className="splash">
        <Loading />
      </div>
    );
  }
  if (!me) {
    if (needsSignIn) return <LoginPage />;
    return <UnavailablePage message={unavailable ?? "The service is not reachable."} />;
  }

  const home = ["home", "insights"].find((s) => me.navigation.some((p) => p.slug === s)) ?? me.navigation[0]?.slug;

  // After sign-in: choose a module. Module 1 (Head Office, Pocket HRMS) = the screens below in <Layout>, unchanged;
  // Module 2 (Field Sales, Bizom) lives under /sales.
  return (
    <Routes>
      <Route index element={<Navigate to="/modules" replace />} />
      <Route path="modules" element={<ModulesPage headOfficeHome={home} />} />
      <Route path="sales/*" element={<SalesHomePage />} />
      <Route element={<Layout />}>
        {me.navigation.map((page) => {
          const Screen = SCREENS[page.slug];
          return Screen ? <Route key={page.slug} path={page.slug} element={<Screen />} /> : null;
        })}
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
