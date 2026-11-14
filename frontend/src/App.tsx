import type { ComponentType } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "./auth/AuthContext";
import { Layout } from "./components/Layout";
import { Loading } from "./components/ui";
import { DashboardPage } from "./pages/DashboardPage";
import { LoginPage } from "./pages/LoginPage";
import { NotFoundPage, PlaceholderPage } from "./pages/PlaceholderPage";
import { ConfigurationPage, HealthPage } from "./pages/SystemPages";
import { UsersPage } from "./pages/UsersPage";

// Implemented pages by slug. Routes exist only for pages the API lists for this user;
// the API independently enforces permissions on every data call.
const IMPLEMENTED: Record<string, ComponentType> = {
  dashboard: DashboardPage,
  users: UsersPage,
  "system-health": HealthPage,
  "system-config": ConfigurationPage,
};

export function App() {
  const { me, loading } = useAuth();

  if (loading) {
    return (
      <div className="login-screen">
        <Loading />
      </div>
    );
  }
  if (!me) return <LoginPage />;

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
