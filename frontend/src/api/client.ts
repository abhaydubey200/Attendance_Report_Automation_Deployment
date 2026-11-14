// Minimal API client. The session lives in an httpOnly cookie (never readable by JS).
// Every request sends X-APIS-Request: 1, which the API requires on state-changing calls (CSRF guard).

const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

type UnauthorizedListener = () => void;
const unauthorizedListeners = new Set<UnauthorizedListener>();

export function onUnauthorized(listener: UnauthorizedListener): () => void {
  unauthorizedListeners.add(listener);
  return () => unauthorizedListeners.delete(listener);
}

/** URL for a plain GET (downloads, links). GETs need no CSRF header; the cookie rides along. */
export function apiUrl(path: string, params?: Record<string, string | number | boolean | null | undefined>): string {
  const query = params
    ? Object.entries(params)
        .filter(([, v]) => v !== undefined && v !== null && v !== "")
        .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
        .join("&")
    : "";
  return `${API_BASE}/api${path}${query ? `?${query}` : ""}`;
}

export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const isForm = typeof FormData !== "undefined" && init.body instanceof FormData;
  const response = await fetch(`${API_BASE}/api${path}`, {
    ...init,
    credentials: "include",
    headers: {
      ...(isForm ? {} : { "Content-Type": "application/json" }),
      "X-APIS-Request": "1",
      ...(init.headers ?? {}),
    },
  });

  if (response.status === 401 && !path.startsWith("/v1/auth/login")) {
    unauthorizedListeners.forEach((l) => l());
  }
  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try {
      const body = await response.json();
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(response.status, detail);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const api = {
  get: <T>(path: string) => apiFetch<T>(path),
  post: <T>(path: string, body?: unknown) =>
    apiFetch<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) }),
  upload: <T>(path: string, form: FormData) => apiFetch<T>(path, { method: "POST", body: form }),
};
