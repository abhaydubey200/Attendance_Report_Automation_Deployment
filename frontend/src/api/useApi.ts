import { useCallback, useEffect, useState } from "react";
import { ApiError, api } from "./client";

export interface ApiState<T> {
  data: T | null;
  error: ApiError | null;
  loading: boolean;
  reload: () => void;
}

/** Fetch a GET endpoint; refetches when `path` changes or `reload()` is called. Pass null to skip. */
export function useApi<T>(path: string | null): ApiState<T> {
  const [tick, setTick] = useState(0);
  const [state, setState] = useState<Omit<ApiState<T>, "reload">>({ data: null, error: null, loading: path !== null });

  useEffect(() => {
    if (path === null) {
      setState({ data: null, error: null, loading: false });
      return;
    }
    let cancelled = false;
    setState((s) => ({ ...s, error: null, loading: true }));
    api
      .get<T>(path)
      .then((data) => !cancelled && setState({ data, error: null, loading: false }))
      .catch((error: unknown) => {
        if (cancelled) return;
        const err = error instanceof ApiError ? error : new ApiError(0, "Network error");
        setState({ data: null, error: err, loading: false });
      });
    return () => {
      cancelled = true;
    };
  }, [path, tick]);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { ...state, reload };
}

/** Build "/v1/x?a=1&b=2", dropping empty values. */
export function withQuery(path: string, params: Record<string, string | number | null | undefined>): string {
  const q = Object.entries(params)
    .filter(([, v]) => v !== undefined && v !== null && v !== "")
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
    .join("&");
  return q ? `${path}?${q}` : path;
}

/** Run a mutating call, track busy/error/message state for a form or button. */
export function useAction() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const run = useCallback(async <R,>(fn: () => Promise<R>, success?: string | ((r: R) => string)): Promise<R | null> => {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const result = await fn();
      if (success) setMessage(typeof success === "function" ? success(result) : success);
      return result;
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Unable to reach the server.");
      return null;
    } finally {
      setBusy(false);
    }
  }, []);
  return { busy, error, message, run, setError, setMessage };
}
