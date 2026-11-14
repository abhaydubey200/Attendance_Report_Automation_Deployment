import { useEffect, useState } from "react";
import { ApiError, api } from "./client";

export interface ApiState<T> {
  data: T | null;
  error: ApiError | null;
  loading: boolean;
}

/** Fetch a GET endpoint once per path. */
export function useApi<T>(path: string): ApiState<T> {
  const [state, setState] = useState<ApiState<T>>({ data: null, error: null, loading: true });

  useEffect(() => {
    let cancelled = false;
    setState({ data: null, error: null, loading: true });
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
  }, [path]);

  return state;
}
