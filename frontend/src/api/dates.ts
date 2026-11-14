import { useEffect, useState } from "react";
import { api } from "./client";
import type { AttendanceSummary } from "./types";

/** ISO date (YYYY-MM-DD) in IST, offset by `days`. */
export function istIso(days = 0): string {
  const now = new Date(Date.now() + 5.5 * 3600_000 + days * 86_400_000);
  return now.toISOString().slice(0, 10);
}

export function shiftIso(iso: string, days: number): string {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

/** Default reporting date: the latest processed date if any, else yesterday (D-1, IST). */
export function useDefaultDate(): [string, (d: string) => void] {
  const [day, setDay] = useState<string>("");
  useEffect(() => {
    let cancelled = false;
    api
      .get<AttendanceSummary>("/v1/dashboard/summary")
      .then((s) => !cancelled && setDay((cur) => cur || s.run?.reporting_date || istIso(-1)))
      .catch(() => !cancelled && setDay((cur) => cur || istIso(-1)));
    return () => {
      cancelled = true;
    };
  }, []);
  return [day, setDay];
}
