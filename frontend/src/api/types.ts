// Mirrors api/schemas.py (API v1).

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

export interface Kpi {
  key: string;
  label: string;
  value: number | null;
  status: string;
}

export interface DashboardSummary {
  today_ist: string;
  reporting_date: string | null;
  last_successful_run: string | null;
  latest_run_status: string | null;
  uploaded_dataset_count: number;
  rule_version: string;
  rule_approval_status: string;
  rules_approved: boolean;
  kpis: Kpi[];
  message: string;
}

export interface HealthItem {
  name: string;
  status: "OK" | "WARN" | "FAIL";
  detail: string;
}

export interface KeyValue {
  key: string;
  value: string;
}

export interface DatasetRow {
  dataset_id: string;
  dataset_name: string;
  source_system: string;
  frequency: string;
  active: boolean;
  schema_status: string;
  columns_defined: number;
}

export interface SourceAuthorityRow {
  domain: string;
  proposed_source: string | null;
  authoritative_source: string | null;
}

export interface SystemConfig {
  application: KeyValue[];
  datasets: DatasetRow[];
  rule_version: string;
  rule_approval_status: string;
  rules: KeyValue[];
  source_authority: SourceAuthorityRow[];
}

export interface UserRow {
  user_id: number;
  username: string;
  display_name: string;
  roles: string[];
  departments: string[];
  is_active: boolean;
  last_login_at: string | null;
}

export interface RoleRow {
  role: string;
  description: string;
  permissions: string[];
}

// ---------------------------------------------------------------- Phases 2-12

export type Counts = Record<string, number>;

export interface Kpis {
  active_employees: number | null;
  eligible_employees: number;
  counts: Counts;
  pending_review: number;
  attendance_pct: number | null;
  absenteeism_pct: number | null;
  percentages_status: string;
}

export interface RunInfo {
  run_id: number;
  run_ref: string;
  reporting_date: string;
  state: string;
  rule_version: string;
  rules_approved: boolean;
  finished_at: string | null;
  ai_status: string | null;
}

export interface GroupStat {
  eligible: number;
  counts: Counts;
  attendance_pct: number | null;
  absenteeism_pct: number | null;
}

export interface TrendPoint extends GroupStat {
  date: string;
}

export interface AttendanceSummary {
  today_ist?: string;
  rule_version?: string;
  rule_approval_status?: string;
  rules_approved?: boolean;
  message?: string | null;
  run: RunInfo | null;
  kpis?: Kpis;
  departments?: (GroupStat & { department_code: string; department_name: string })[];
  locations?: (GroupStat & { location_code: string })[];
  trend?: TrendPoint[];
  exceptions?: { open: number; by_category: Counts; critical: number };
  data_quality?: {
    uploaded_datasets: number;
    missing_datasets: string[];
    invalid_records: number;
    unmapped_employees: number | null;
    conflicting_records: number | null;
  };
  last_successful_run?: RunInfo | null;
}

export interface FactRow {
  employee_code: string;
  employee_name: string | null;
  department_code: string | null;
  location_code: string | null;
  date: string;
  status: string;
  bizom_status: string | null;
  hrms_status: string | null;
  leave_status: string | null;
  first_in: string | null;
  last_out: string | null;
  punch_count: number;
  record_status: string;
  reason: string | null;
}

export interface SchemaDef {
  columns: Record<string, string>;
  primary_key: string[];
  date_formats: string[];
  datetime_formats: string[];
  time_formats: string[];
  value_maps: Record<string, Record<string, string>>;
  check_reporting_period: boolean;
}

export interface DatasetInfo {
  dataset_id: string;
  dataset_name: string;
  source_system: string;
  frequency: string;
  active: boolean;
  kind: string;
  schema_version: number | null;
  schema_status: string;
  schema: SchemaDef | null;
  schema_notes: string | null;
  schema_by: string | null;
}

export interface FieldCatalog {
  kinds: Record<string, { field: string; type: string; required: boolean }[]>;
  dataset_kind: Record<string, string>;
  value_maps: Record<string, string[]>;
}

export interface IssueRow {
  row_number: number | null;
  column_name: string | null;
  code: string;
  severity: string;
  message: string;
}

export interface InspectResult {
  accepted: boolean;
  errors?: string[];
  token?: string;
  sheets?: string[];
  sheet?: string | null;
  columns?: string[];
  row_count?: number;
  preview?: Record<string, string>[];
  profile?: { column: string; blank: number; distinct: number; samples: string[] }[];
  schema_version?: number | null;
  schema_defined?: boolean;
  validation?: {
    status: string;
    total_rows: number;
    valid_rows: number;
    invalid_rows: number;
    duplicate_rows: number;
    empty_rows: number;
    warning_count: number;
    error_count: number;
    issues_by_code: Counts;
    issues: IssueRow[];
  } | null;
  duplicate_of?: { upload_id: number; uploaded_at: string; dataset_id: string } | null;
  current_upload?: { upload_id: number; original_filename: string } | null;
  can_confirm?: boolean;
  sha256?: string;
}

export interface UploadInfo {
  upload_id: number;
  dataset_id: string;
  source_system: string;
  reporting_date: string;
  original_filename: string;
  sha256: string;
  size_bytes: number;
  schema_version: number | null;
  status: string;
  validation_status: string;
  total_rows: number;
  valid_rows: number;
  invalid_rows: number;
  duplicate_rows: number;
  warning_count: number;
  standardized_rows: number;
  is_current: boolean;
  reprocess_of: number | null;
  superseded_by: number | null;
  uploaded_by: string;
  uploaded_at: string;
  issues?: IssueRow[];
}

export interface RunRow {
  run_id: number;
  run_ref: string;
  reporting_date: string;
  version_no: number;
  state: string;
  is_current: boolean;
  rule_version: string;
  rules_approved: boolean;
  ai_status: string | null;
  error: string | null;
  started_by: string;
  started_at: string;
  finished_at: string | null;
  approved_by: string | null;
}

export interface RunDetail extends RunRow {
  stats: { kpis?: Kpis; missing_datasets?: string[]; reconciliation?: { counts: Counts; exceptions: number; reconciliation_rate: number | null } };
  logs: { stage: string; outcome: string; started_at: string; duration_ms: number | null; record_count: number | null; message: string | null }[];
}

export interface MappingRow {
  mapping_id: number;
  source_system: string;
  source_employee_id: string;
  source_employee_name: string | null;
  status: string;
  method: string | null;
  employee_key: number | null;
  employee: string | null;
  suggested_employee_key: number | null;
  suggested_employee: string | null;
  confidence: number | null;
  reviewed_by: string | null;
}

export interface EmployeeRow {
  employee_key: number;
  employee_code: string;
  employee_name: string | null;
  department_code: string | null;
  location_code: string | null;
  designation: string | null;
  employment_status: string | null;
  joining_date: string | null;
  exit_date: string | null;
}

export interface ExceptionRow {
  exception_id: number;
  run_id: number;
  source_employee_id: string | null;
  employee_key: number | null;
  department_code: string | null;
  date: string;
  category: string;
  severity: string;
  source_values: { bizom: string | null; hrms: string | null; detail: string };
  status: string;
  assigned_to: string | null;
  resolution: string | null;
  resolved_status: string | null;
  resolution_comment: string | null;
  resolved_by: string | null;
  resolved_at: string | null;
}

export interface ReconRow {
  id: number;
  category: string;
  source_employee_id: string | null;
  date: string;
  bizom: string | null;
  hrms: string | null;
  detail: string | null;
}

export interface ReportRow {
  report_id: number;
  run_id: number;
  run_ref: string | null;
  reporting_date: string | null;
  report_type: string;
  department_code: string | null;
  file_format: string;
  report_version: number;
  provisional: boolean;
  status: string;
  generated_by: string;
  generated_at: string;
}

export interface AskResult {
  text: string;
  table: { header: string[]; rows: (string | number | null)[][] } | null;
  intent: string | null;
  source: string | null;
  period: string | null;
  supported_questions: string[];
  phrased_by_ai?: boolean;
}
