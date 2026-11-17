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
  counts: Record<Status, number>;   // WEEK_OFF / WFH may be missing on older days
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
  flexi_until?: string | null;
  early_before: string;
  min_work_hours: number;
  long_work_hours: number;
  on_duty_codes: string[];
  no_punch_with_shift: "ABSENT" | "NOT_TRACKED";
  no_punch_no_shift: "ABSENT" | "NOT_TRACKED";
  single_punch_counts_present: boolean;
  exclude_codes: string[];
  always_present_codes?: string[];
  out_of_scope_categories?: string[];
}

export interface Insights {
  report_date: string;
  excluded: number;
  categories: string[];
  by_category: Record<string, Summary>;
  departments?: string[];
  hods?: HodInsight[];
  sources?: { hrms?: boolean; permission_file?: boolean;
    permissions?: { rows: number; today: number; approved: number; pending: number; other_dates: number; excused_late: number; excused_early: number; not_in_file: number } };
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
  permission?: string;
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

export interface DayDetail {
  upload_id: number;
  report_date: string;
  file: string | null;
  permission_file?: string | null;
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
  mail: MailItem[];
  master_import?: ImportResult | null;
  send_mode?: "auto" | "manual";
}

export interface UploadOptions {
  default_mode: "auto" | "manual";
  test_recipient: string | null;
  test_cc?: string[];
  wait_for_permission: boolean;
  mode: "test" | "live";
  can_import_master: boolean;
  employees: number;
}

export interface DayListItem {
  report_date: string;
  employees: number;
  attendance_pct: number | null;
  has_hrms?: boolean;
  has_permission?: boolean;
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
  approval_required: boolean;
  auto_send: boolean;
  wait_for_permission: boolean;
  sender: string | null;
  reply_to: string | null;
  subject_prefix: string;
  attach_excel: boolean;
  attach_dashboard: boolean;
  retry_attempts: number;
  team_emails: boolean;
  hod_summary: boolean;
  director_report: boolean;
  hr_exceptions: boolean;
  hod_cc_on_team: boolean;
  hr_cc_on_hod_summary: boolean;
  test_recipient: string | null;
  test_cc: string[];
  director_name: string;
  director_emails: string[];
  hr_emails: string[];
}

export interface SettingsData {
  rules: Rules;
  email: EmailSettings;
  secrets: Record<string, boolean>;
  categories: string[];
  public_url: string | null;
}

export type MailStatus = "PENDING" | "SENT" | "SAVED" | "FAILED" | "HELD" | "DISABLED" | "DUPLICATE" | "SUPERSEDED" | "TEST_SENT";

export interface MailCounts {
  total: number;
  present: number;
  absent: number;
  leave: number;
  od: number;
  wfh: number;
  late: number;
  missing_punch: number;
  week_off: number;
  not_tracked: number;
  no_record: number;
  attendance_pct: number | null;
  attention: number;
}

export interface MailItem {
  id: number;
  report_date: string;
  key: string;
  name: string;
  role: string;
  to: string;
  cc: string;
  subject: string;
  status: MailStatus;
  /** can still be approved / sent (in live mode this includes emails only saved to the outbox in test mode) */
  sendable: boolean;
  note: string | null;
  attempts: number;
  team: number;
  summary: number;
  company: number;
  exceptions: number;
  attention: number;
  counts: { team: MailCounts; summary: MailCounts | null; company: MailCounts | null; exceptions: number };
  sent_at: string | null;
  approved_by: string | null;
}

export interface DayMail {
  report_date: string;
  mode: "test" | "live";
  approval_required: boolean;
  test_recipient: string | null;
  test_cc?: string[];
  items: MailItem[];
  status: Partial<Record<MailStatus, number>>;
  planned: boolean;
  sent_now?: number;
}

export interface RoutingOverview {
  employees: number;
  detail_total: number;
  routed_to_people: number;
  routed_to_director: number;
  unique: boolean;
  recipients: { key: string; name: string; role: string; to: string[]; cc: string[]; team: number; summary: number; status: string; note: string | null }[];
  held: { code: string; name: string; department: string; hod: string; issue: string | null }[];
  rules: Record<string, number>;
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
  routing_issue: string;
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
  routing?: {
    config?: { applied: Record<string, boolean | string>; disabled: string[] };
    recipients?: { imported: number; switched_off: number };
    coverage?: { checked: number; differences: number; examples: { code: string; issue: string }[] };
  };
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
  permission: string;
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


