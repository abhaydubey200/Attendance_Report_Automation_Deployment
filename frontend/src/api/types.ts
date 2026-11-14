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
