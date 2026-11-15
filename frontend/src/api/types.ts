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

export type Status = "PRESENT" | "MISSING_PUNCH" | "ON_DUTY" | "HALF_DAY" | "LEAVE" | "ABSENT" | "NOT_TRACKED";

export interface Summary {
  employees: number;
  tracked: number;
  counts: Record<Status, number>;
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

export interface ScopeInsights {
  summary: Summary;
  highlights: Highlight[];
  arrivals: { label: string; count: number }[];
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
}

export interface Insights {
  report_date: string;
  excluded: number;
  categories: string[];
  by_category: Record<string, Summary>;
  scopes: Record<string, ScopeInsights>;
  previous_date: string | null;
  rules: Rules;
}

export interface EmployeeRow {
  code: string;
  name: string;
  category: string;
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
  file: string;
  uploaded_by: string;
  uploaded_at: string;
  employees: number;
  insights: Insights;
  emails: { scope: string; recipients: string; status: string; mode: string; error: string | null; sent_at: string; sent_by: string }[];
  rows?: EmployeeRow[];
}

export interface UploadResult extends DayDetail {
  auto_sent: boolean;
  email_results: EmailResult[];
}

export interface DayListItem {
  report_date: string;
  employees: number;
  attendance_pct: number | null;
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
