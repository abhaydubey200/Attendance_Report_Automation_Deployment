import type { ComponentType } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "./auth/AuthContext";
import { Layout } from "./components/Layout";
import { Loading } from "./components/ui";
import { DashboardPage } from "./pages/DashboardPage";
import { LoginPage, UnavailablePage } from "./pages/LoginPage";
import { NotFoundPage, PlaceholderPage } from "./pages/PlaceholderPage";
import { ConfigurationPage, HealthPage } from "./pages/SystemPages";
import { UsersPage } from "./pages/UsersPage";
import { AppLogsPage, AppSettingsPage, AttendanceRulesPage, DepartmentMappingPage, EmployeeMappingPage, HierarchyPage, ProcessingRunsPage } from "./pages/AdminPages";
import { AiSummaryPage, AnalystPage } from "./pages/AiPages";
import { AbsenteeismPage, DailyAttendancePage, DepartmentAnalyticsPage, EmployeeAttendancePage, LeaveAnalyticsPage, MissingPunchesPage } from "./pages/AnalyticsPages";
import { DataQualityPage, DatasetRegistryPage, UploadHistoryPage, UploadPage } from "./pages/DataPages";
import { ConflictsPage, ExceptionResolutionPage, SourceComparisonPage, UnmappedEmployeesPage } from "./pages/ReconciliationPages";
import { ReportsPage } from "./pages/ReportPages";

// Implemented pages by slug. Routes exist only for pages the API lists for this user;
// the API independently enforces permissions on every data call.
const IMPLEMENTED: Record<string, ComponentType> = {
  dashboard: DashboardPage,
  users: UsersPage,
  "system-health": HealthPage,
  "system-config": ConfigurationPage,
  upload: UploadPage,
  "dataset-registry": DatasetRegistryPage,
  "upload-history": UploadHistoryPage,
  "data-quality": DataQualityPage,
  "daily-attendance": DailyAttendancePage,
  "employee-attendance": EmployeeAttendancePage,
  "department-analytics": DepartmentAnalyticsPage,
  absenteeism: AbsenteeismPage,
  "leave-analytics": LeaveAnalyticsPage,
  "missing-punches": MissingPunchesPage,
  "source-comparison": SourceComparisonPage,
  conflicts: ConflictsPage,
  "unmapped-employees": UnmappedEmployeesPage,
  "exception-resolution": ExceptionResolutionPage,
  "hod-reports": () => <ReportsPage mode="hod" />,
  "directors-reports": () => <ReportsPage mode="directors" />,
  "report-preview": () => <ReportsPage mode="preview" />,
  "report-history": () => <ReportsPage mode="history" />,
  "ai-summary": AiSummaryPage,
  "ai-analyst": AnalystPage,
  "department-mapping": DepartmentMappingPage,
  "employee-mapping": EmployeeMappingPage,
  "attendance-rules": AttendanceRulesPage,
  "reporting-hierarchy": HierarchyPage,
  "app-settings": AppSettingsPage,
  "processing-runs": ProcessingRunsPage,
  "app-logs": AppLogsPage,
};

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
    return <UnavailablePage message={unavailable ?? "The MIS service is not reachable."} />;
  }

  const home = me.navigation[0]?.slug;

  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={home ? <Navigate to={`/${home}`} replace /> : <NotFoundPage />} />
        {me.navigation.map((page) => {
          const Page = IMPLEMENTED[page.slug];
          return <Route key={page.slug} path={page.slug} element={Page ? <Page /> : <PlaceholderPage page={page} />} />;
        })}
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
