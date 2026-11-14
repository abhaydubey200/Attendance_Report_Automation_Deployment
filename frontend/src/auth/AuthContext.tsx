import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { ApiError, api, onUnauthorized } from "../api/client";
import type { Me } from "../api/types";

interface AuthContextValue {
  me: Me | null;
  loading: boolean;
  notice: string | null;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  hasPermission: (permission: string) => boolean;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<Me>("/v1/auth/me")
      .then(setMe)
      .catch(() => setMe(null))
      .finally(() => setLoading(false));
  }, []);

  // Session expired / revoked server-side: drop to the login screen.
  useEffect(
    () =>
      onUnauthorized(() => {
        setMe((current) => {
          if (current) setNotice("Your session has ended. Please sign in again.");
          return null;
        });
      }),
    [],
  );

  const login = useCallback(async (username: string, password: string) => {
    setNotice(null);
    const profile = await api.post<Me>("/v1/auth/login", { username, password });
    setMe(profile);
  }, []);

  const logout = useCallback(async () => {
    try {
      await api.post<void>("/v1/auth/logout");
    } catch (error) {
      if (!(error instanceof ApiError)) throw error;
    }
    setMe(null);
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      me,
      loading,
      notice,
      login,
      logout,
      hasPermission: (permission) => !!me?.permissions.includes(permission),
    }),
    [me, loading, notice, login, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
