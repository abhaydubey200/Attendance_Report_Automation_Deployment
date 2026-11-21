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
  geo?: Record<string, string[]>; geo_summary?: SalesGeoSummary; risk?: Record<string, number>;
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
  geo_in_emails: boolean; keep_months: number; geo_away_outlet_m: number; geo_away_outlet_min: number; geo_same_spot_m: number;
  geo_same_spot_min_calls: number; geo_cluster_m: number; geo_cluster_outlets: number; geo_cluster_outlet_far_m: number;
  geo_km_ratio: number; geo_km_extra: number; geo_start_away_km: number; geo_start_history_days: number; geo_start_min_days: number;
  geo_end_away_km: number; geo_offbeat_min: number; geo_together_m: number; geo_together_minutes: number; geo_together_share: number;
  geo_together_min_calls: number; photo_downloads: boolean; photo_batch: number; photo_same_bits: number; photo_reuse_bits: number;
  photo_dark: number; photo_blurry: number; photo_time_hours: number;
}

export interface SalesEmailSettings {
  mode: "test" | "live"; approval_required: boolean; auto_send: boolean; test_recipient: string | null; director_name: string; director_emails: string[];
  hr_emails: string[]; always_bcc: string[]; levels: string[]; attach_excel: boolean; attach_dashboard: boolean;
}

export const STATUS_COLOR: Record<SalesStatus, string> = {
  PRESENT: "#16a34a", LATE: "#d97706", HALF_DAY: "#f59e0b", LEAVE: "#64748b", WEEK_OFF: "#94a3b8", ABSENT: "#dc2626",
};

export interface SalesWarnCount { code: string; label: string; level: "high" | "medium" | "low"; days: number }

export interface SalesReportPerson {
  code: string; name: string; designation: string; zone: string; team_head: string; hod: string; days: number; present: number; late: number;
  half_day: number; leave: number; week_off: number; absent: number; attendance_pct: number | null; avg_market: string; km: number;
  flag_days: number; warnings: SalesWarnCount[]; repeat: string[];
}

export interface SalesReport {
  from: string; to: string; days_uploaded: number; people: SalesReportPerson[]; repeat_days: number;
  days: { date: string; people: number; attendance_pct: number | null; present: number; late: number; absent: number; flagged: number }[];
  totals: { attendance_pct: number | null; person_days: number; flagged_days: number; repeat_people: number; absent: number; late: number; leave: number };
  filters: { hods: string[]; teams: string[] };
}

export interface SalesEmployeeReport {
  code: string; name: string; designation: string; team_head: string; team_head_email: string; hod: string; status: string; from: string; to: string;
  summary: { days: number; present: number; late: number; half_day: number; leave: number; week_off: number; absent: number; attendance_pct: number | null; flagged_days: number };
  days: { date: string; status: SalesStatus; status_label: string; leave: string; not_marked: boolean; att: string; first: string; last: string;
    market: string; km: number | null; eod: string; calls: number | null; productive: number | null; warnings: string[] }[];
}

export interface SalesEmailLogRow {
  id: number; report_date: string; kind: "Daily" | "Month-end"; recipient: string; role: string; to: string; subject: string; status: string;
  note: string | null; sent_at: string; sent_by: string | null;
}

export interface SalesJobRun {
  id: number; job: string; target: string | null; trigger: string; status: string; summary: Record<string, unknown> | null; error: string | null;
  started_by: string; started_at: string; finished_at: string | null; seconds: number | null;
}

export interface SalesJobs { inbox: string; waiting: string[]; auto_send: boolean; mode: "test" | "live"; runs: SalesJobRun[] }

export interface SalesMonthList { months: { month: string; label: string; days: number; emails: number }[]; default: string }
export interface SalesMonthMail { month: string; label: string; mode: "test" | "live"; testing: string | null; items: SalesMailItem[] }

// ---------------------------------------------------------------- location checks
export type GeoLevel = "high" | "medium" | "low";
export interface GeoSign { code: string; label: string; level: GeoLevel; why: string; evidence: string; kind: "location" | "day" | "photo" }
export interface GeoPoint { lat: number; lng: number; time: string | null }
export interface GeoCall {
  seq: number; start: string | null; end: string | null; duration_s: number | null; lat: number | null; lng: number | null;
  outlet: string | null; outlet_lat: number | null; outlet_lng: number | null; beat: string | null; distance_m: number | null;
  productive: boolean; away: boolean; fast: boolean; leg: { km: number; minutes: number; kmh: number } | null;
}
export interface GeoCase { code: string; date: string; status: "OPEN" | "OK" | "ACTION"; status_label: string; note: string; reviewed_by: string | null; reviewed_at: string | null }
export interface GeoDayMap {
  date: string; code: string; name: string; designation: string; manager: string; hod: string; status: SalesStatus;
  attendance_time: string | null; eod_time: string | null; km: number | null; market_minutes: number | null; photo_url: string | null;
  attendance: GeoPoint | null; day_end: GeoPoint | null; usual_start: { lat: number; lng: number; days: number; limit_km: number } | null;
  calls: GeoCall[]; signs: GeoSign[]; case: GeoCase; photos: PhotoItem[];
  usual_places: { lat: number; lng: number; days: number; radius_km: number; limit_km: number }[];
  score: { risk: number; unusual: boolean; anomaly: number | null; reasons: string[] };
}
export interface GeoCaseRow {
  date: string; code: string; name: string; designation: string; manager: string; hod: string; signs: GeoSign[]; other_signs: string[];
  high: number; case: GeoCase; photo_signs: GeoSign[]; risk: number;
}
export interface GeoCases { from: string; to: string; cases: GeoCaseRow[]; hods: string[]; labels: Record<string, string> }
export interface SalesGeoSummary { people: number; signs: { code: string; label: string; level: GeoLevel; n: number }[]; points: boolean; calls: boolean }


// ---------------------------------------------------------------- selfie checks
export interface PhotoItem {
  id: number; url: string; code: string; name: string; date: string; att_time: string | null; status: string; error: string | null;
  faces: number | null; width: number | null; height: number | null; size_kb: number | null; exif_time: string | null; signs: GeoSign[];
  matches: { id: number; url: string; code: string; name: string; date: string }[];
}
export interface PhotosOverview {
  from: string; to: string; photos: number; checked: number; flagged: number; people: number;
  queue: { waiting: number; done: number; failed: number; skipped: number };
  signs: { code: string; label: string; level: GeoLevel; why: string; n: number }[]; items: PhotoItem[]; shown: number;
}
