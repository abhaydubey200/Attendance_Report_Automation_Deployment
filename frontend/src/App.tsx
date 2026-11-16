import type { ComponentType } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "./auth/AuthContext";
import { Layout } from "./components/Layout";
import { Loading, Notice, PageHeader } from "./components/ui";
import { AutomationPage } from "./pages/AutomationPage";
import { EmailsPage } from "./pages/EmailsPage";
import { MailPage } from "./pages/MailPage";
import { EmployeesPage } from "./pages/EmployeesPage";
import { EmployeeReportPage, ReportsPage } from "./pages/ReportsPage";
import { InsightsPage } from "./pages/InsightsPage";
import { LoginPage, UnavailablePage } from "./pages/LoginPage";
import { SettingsPage } from "./pages/SettingsPage";
import { UploadPage } from "./pages/UploadPage";

// Routes exist only for screens the API lists for this user; the API checks permissions on every call.
const SCREENS: Record<string, ComponentType> = {
  upload: UploadPage,
  insights: InsightsPage,
  mail: MailPage,
  emails: EmailsPage,
  employees: EmployeesPage,
  automation: AutomationPage,
  reports: ReportsPage,
  "employee-report": EmployeeReportPage,
  settings: SettingsPage,
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

  const home = me.navigation.some((p) => p.slug === "insights") ? "insights" : me.navigation[0]?.slug;

  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={home ? <Navigate to={`/${home}`} replace /> : <NotFoundPage />} />
        {me.navigation.map((page) => {
          const Screen = SCREENS[page.slug];
          return Screen ? <Route key={page.slug} path={page.slug} element={<Screen />} /> : null;
        })}
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
