// Module 2 - Field Sales (Bizom) API types.

export type SalesStatus = "PRESENT" | "LATE" | "HALF_DAY" | "LEAVE" | "WEEK_OFF" | "ABSENT";

export interface SalesFlag { code: string; label: string; level: "high" | "medium" | "low"; why: string }

export interface SalesPerson {
  code: string; name: string; designation: string; zone: string; manager: string; zonal: string; hod: string;
  status: SalesStatus; status_label: string; not_marked: boolean; leave: string; att: string; first: string; last: string;
  market: string; market_min: number | null; km: number | null; eod: string; calls: number | null; productive: number | null;
  order_value: number | null; in_master: boolean; flags: SalesFlag[]; evidence: string;
}

export interface SalesWarning { code: string; label: string; level: "high" | "medium" | "low"; why: string; n: number }
export interface SalesTeam { hod: string; zonal: string; people: number; pct: number | null; absent: number; late: number; flagged: number }

export interface SalesSummary {
  date: string; people: number; counts: Record<SalesStatus, number>; not_marked: number; attendance_pct: number | null;
  avg_attendance_time: string | null; avg_market_minutes: number | null; warnings: Record<string, number>;
  people_flagged: number; people_high: number;
  calls: { people: number; calls: number; productive: number; order_value: number } | null;
  files: { attendance: boolean; eod: boolean; calls: boolean };
  data: { not_in_staff_list: string[]; left_but_marked: string[]; excluded: Record<string, number>; skipped_rows: number;
    eod_not_marked: number; calls_people_not_in_file: string[] };
}

export interface SalesMailItem {
  id: number; report_date: string; key: string; name: string; role: string; to: string; subject: string; status: string;
  note: string | null; attempts: number; sendable: boolean; sent_at: string | null; approved_by: string | null;
  counts: { people?: number; absent?: number; late?: number; flagged?: number; attendance_pct?: number | null };
}

export interface SalesDay {
  report_date: string; people: number; summary: SalesSummary; files: { attendance: string | null; eod: string | null; calls: string | null };
  uploaded_by: string; uploaded_at: string; rows: SalesPerson[]; warnings: SalesWarning[]; teams: SalesTeam[]; mail: SalesMailItem[];
}

export interface SalesDayRow {
  report_date: string; people: number; attendance_pct: number | null; absent: number; late: number; flagged: number;
  files: { attendance: boolean; eod: boolean; calls: boolean } | null; uploaded_by: string; uploaded_at: string;
}

export interface SalesDayMail { report_date: string; mode: "test" | "live"; testing: string | null; items: SalesMailItem[] }

export interface SalesStaffRow {
  code: string; name: string; designation: string | null; zone: string | null; hq: string | null; channel: string | null;
  manager_name: string | null; manager_email: string | null; asm_name: string | null; asm_email: string | null;
  zonal_name: string | null; zonal_email: string | null; hod_name: string | null; hod_email: string | null;
  date_of_joining: string | null; status: "ACTIVE" | "LEFT"; exit_date: string | null;
}

export interface SalesStaff {
  summary: { total: number; active: number; left: number; with_email: Record<string, number>; no_route: number;
    hods: { name: string; email: string; people: number }[]; zonal: { name: string; email: string; people: number }[] };
  staff: SalesStaffRow[];
}

export interface SalesRules {
  late_after: string; half_day_from: string; not_marked_is_absent: boolean; include_promoters: boolean; promoter_codes: string[];
  exclude_codes: string[]; supervisor_designations: string[]; short_market_minutes: number; very_short_market_minutes: number;
  late_start_minutes: number; high_km: number; attendance_far_m: number; short_day_minutes: number; short_call_seconds: number;
  short_calls_min: number; far_call_m: number; max_speed_kmh: number; calls_after: string; beat_jump_min: number;
}

export interface SalesEmailSettings {
  mode: "test" | "live"; approval_required: boolean; test_recipient: string | null; director_name: string; director_emails: string[];
  hr_emails: string[]; always_bcc: string[]; levels: string[]; attach_excel: boolean; attach_dashboard: boolean;
}

export const STATUS_COLOR: Record<SalesStatus, string> = {
  PRESENT: "#16a34a", LATE: "#d97706", HALF_DAY: "#f59e0b", LEAVE: "#64748b", WEEK_OFF: "#94a3b8", ABSENT: "#dc2626",
};
