import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { ApiError, api, onUnauthorized } from "../api/client";
import type { Me } from "../api/types";

/**
 * Session state.
 *  - auth_mode "none"  (default): the API identifies the local operator; there is no login page.
 *  - auth_mode "local": a 401 from /auth/me means "show the sign-in form".
 */
interface AuthContextValue {
  me: Me | null;
  loading: boolean;
  needsSignIn: boolean;
  unavailable: string | null;
  notice: string | null;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  hasPermission: (permission: string) => boolean;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  const [needsSignIn, setNeedsSignIn] = useState(false);
  const [unavailable, setUnavailable] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<Me>("/v1/auth/me")
      .then((profile) => {
        setMe(profile);
        setNeedsSignIn(false);
      })
      .catch((error: unknown) => {
        if (error instanceof ApiError && error.status === 401) setNeedsSignIn(true);
        else setUnavailable("The MIS service is not reachable. Please make sure the server is running.");
      })
      .finally(() => setLoading(false));
  }, []);

  // Session expired / revoked server-side (sign-in mode only).
  useEffect(
    () =>
      onUnauthorized(() => {
        setMe((current) => {
          if (current) setNotice("Your session has ended. Please sign in again.");
          return null;
        });
        setNeedsSignIn(true);
      }),
    [],
  );

  const login = useCallback(async (username: string, password: string) => {
    setNotice(null);
    const profile = await api.post<Me>("/v1/auth/login", { username, password });
    setMe(profile);
    setNeedsSignIn(false);
  }, []);

  const logout = useCallback(async () => {
    try {
      await api.post<void>("/v1/auth/logout");
    } catch (error) {
      if (!(error instanceof ApiError)) throw error;
    }
    setMe(null);
    setNeedsSignIn(true);
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      me,
      loading,
      needsSignIn,
      unavailable,
      notice,
      login,
      logout,
      hasPermission: (permission) => !!me?.permissions.includes(permission),
    }),
    [me, loading, needsSignIn, unavailable, notice, login, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
