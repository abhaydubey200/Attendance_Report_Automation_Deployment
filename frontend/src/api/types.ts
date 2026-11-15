// Mirrors the API (v1).

export interface NavPage {
  section: string;
  title: string;
  slug: string;
  implemented: boolean;
  phase: number | null;
}

export interface Me {
  user_id: number;
  username: string;
  display_name: string;
  roles: string[];
  permissions: string[];
  departments: string[];
  navigation: NavPage[];
  environment: string;
  app_name: string;
  idle_timeout_minutes: number;
  auth_mode: "none" | "local";
}

export type Status = "PRESENT" | "MISSING_PUNCH" | "ON_DUTY" | "HALF_DAY" | "LEAVE" | "ABSENT" | "WEEK_OFF" | "NOT_TRACKED";

export interface Summary {
  employees: number;
  tracked: number;
  counts: Record<Status, number>;   // WEEK_OFF may be missing on days analysed before Bizom
  attendance_pct: number | null;
  absent_pct: number | null;
  late: number;
  late_pct: number | null;
  avg_late_minutes: number;
  left_early: number;
  short_hours: number;
  long_hours: number;
  avg_in_time: string | null;
  earliest_in: string | null;
  latest_in: string | null;
  avg_work_hours: number | null;
}

export interface Highlight {
  kind: "good" | "warn" | "bad" | "info";
  text: string;
}

export interface BreakdownRow {
  name: string;
  hod: string | null;
  employees: number;
  tracked: number;
  attendance_pct: number | null;
  present: number;
  absent: number;
  late: number;
  leave: number;
  not_tracked: number;
}

export interface ScopeInsights {
  summary: Summary;
  highlights: Highlight[];
  arrivals: { label: string; count: number }[];
  breakdown?: { by: string; rows: BreakdownRow[] };
}

export interface HodInsight {
  name: string;
  scope: string;
  employees: number;
  departments: string[];
  attendance_pct: number | null;
}

export interface Rules {
  late_after: string;
  early_before: string;
  min_work_hours: number;
  long_work_hours: number;
  on_duty_codes: string[];
  no_punch_with_shift: "ABSENT" | "NOT_TRACKED";
  no_punch_no_shift: "ABSENT" | "NOT_TRACKED";
  single_punch_counts_present: boolean;
  exclude_codes: string[];
  bizom_include_codes?: string[];
}

export interface Insights {
  report_date: string;
  excluded: number;
  categories: string[];
  by_category: Record<string, Summary>;
  departments?: string[];
  hods?: HodInsight[];
  sources?: { hrms?: boolean; bizom_file?: boolean; bizom?: { rows: number; matched: number; decided: number; added: number; skipped: number; excluded: number } };
  master?: { matched: number; not_in_master: number; left_excluded: number; missing_from_file: number } | null;
  scopes: Record<string, ScopeInsights>;
  previous_date: string | null;
  rules: Rules;
}

export interface EmployeeRow {
  code: string;
  name: string;
  category: string;
  department?: string;
  hod?: string;
  team?: string;
  manager?: string;
  source?: string;
  bizom_status?: string;
  designation?: string;
  shift: string;
  in_time: string | null;
  out_time: string | null;
  punches: number;
  work_minutes: number | null;
  work_hours: number | null;
  leave_type: string | null;
  day_portion: string | null;
  status: Status;
  status_label: string;
  late_minutes: number;
  early_minutes: number;
  flags: string[];
}

export interface EmailResult {
  scope: string;
  scope_label: string;
  recipients: string[];
  status: "SENT" | "SAVED" | "FAILED" | "NO_RECIPIENTS";
  detail: string | null;
}

export interface DayDetail {
  upload_id: number;
  report_date: string;
  file: string | null;
  bizom_file?: string | null;
  uploaded_by: string;
  uploaded_at: string;
  employees: number;
  insights: Insights;
  emails: { scope: string; recipients: string; status: string; mode: string; error: string | null; sent_at: string; sent_by: string }[];
  rows?: EmployeeRow[];
}

export interface UploadResult extends DayDetail {
  auto_sent: boolean;
  send_note: string | null;
  email_results: EmailResult[];
}

export interface DayListItem {
  report_date: string;
  employees: number;
  attendance_pct: number | null;
  has_hrms?: boolean;
  has_bizom?: boolean;
  absent: number;
  late: number;
  emails: number;
  email_failed: number;
  uploaded_at: string;
}

export interface EmailLogRow {
  id: number;
  report_date: string;
  scope: string;
  recipients: string;
  subject: string;
  mode: string;
  status: string;
  error: string | null;
  sent_by: string;
  sent_at: string;
}

export interface EmailSettings {
  mode: "test" | "live";
  auto_send: boolean;
  send_to_hods: boolean;
  wait_for_bizom: boolean;
  sender: string | null;
  smtp_host: string | null;
  smtp_port: number;
  smtp_starttls: boolean;
  smtp_username: string | null;
  subject_prefix: string;
  attach_excel: boolean;
  attach_dashboard: boolean;
}

export interface RecipientRow {
  name: string;
  email: string;
  scope: string;
  active: boolean;
}

export interface SettingsData {
  rules: Rules;
  email: EmailSettings;
  smtp_password_set: boolean;
  recipients: RecipientRow[];
  categories: string[];
  public_url: string | null;
}

export interface Employee {
  id: number;
  code: string;
  name: string;
  department: string;
  date_of_joining: string | null;
  hod_name: string;
  hod_email: string;
  team_lead_email: string;
  team: string;
  reporting_manager: string;
  status: "ACTIVE" | "LEFT";
  exit_date: string | null;
  source: string;
  updated_at: string | null;
  updated_by: string | null;
}

export interface EmployeeSummary {
  total: number;
  active: number;
  left: number;
  hods: { name: string; emails: string[]; employees: number; departments: string[] }[];
  departments: string[];
  hods_without_email: string[];
}

export interface EmployeeList {
  employees: Employee[];
  summary: EmployeeSummary;
}

export interface ImportResult {
  rows: number;
  added: number;
  updated: number;
  unchanged: number;
  kept_left: number;
  not_in_file: number;
  problems: string[];
  problem_count: number;
}

export interface EmployeeChange {
  action: string;
  changes: Record<string, [unknown, unknown]>;
  actor: string;
  at: string;
}

/** "HOD:Name" -> "HOD Name"; "ALL" -> "All employees". */
export function scopeLabel(scope: string): string {
  if (scope === "ALL") return "All employees";
  if (scope.startsWith("HOD:")) return `HOD ${scope.slice(4)}`;
  return scope;
}

export interface Tally {
  days: number;
  tracked: number;
  present: number;
  missing_punch: number;
  half_day: number;
  leave: number;
  absent: number;
  week_off: number;
  not_tracked: number;
  late: number;
  left_early: number;
  attendance_pct: number | null;
  avg_in_time: string | null;
  avg_work_hours: number | null;
}

export interface ReportDay {
  date: string;
  code: string;
  name: string;
  category: string;
  department: string;
  hod: string;
  team: string;
  manager: string;
  status: Status;
  status_label: string;
  in_time: string | null;
  out_time: string | null;
  work_hours: number | null;
  late_minutes: number;
  early_minutes: number;
  leave_type: string | null;
  source: string;
  bizom_status: string;
  flags: string[];
}

export interface ReportPerson extends Tally {
  code: string;
  name: string;
  category: string;
  department: string;
  hod: string;
  team: string;
  manager: string;
}

export interface AttendanceReport {
  from: string;
  to: string;
  dates: string[];
  options: Record<"hod" | "department" | "team" | "manager" | "category" | "source", string[]>;
  totals: Tally & { employees: number };
  employees: ReportPerson[];
  days?: ReportDay[];
  days_truncated?: boolean;
}

export interface EmployeeReport {
  employee: { code: string; name: string; department: string; hod_name: string; team: string; reporting_manager: string; status: string | null };
  in_master: boolean;
  from: string;
  to: string;
  summary: Tally;
  days: ReportDay[];
}

export const SOURCE_LABELS: Record<string, string> = { HRMS: "Pocket HRMS", BIZOM: "Bizom", "HRMS+BIZOM": "HRMS + Bizom" };
