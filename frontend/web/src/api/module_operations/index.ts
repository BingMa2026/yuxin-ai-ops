import { request } from "@utils";

export interface OverviewSummary {
  gross_revenue_yuan: number;
  refund_yuan: number;
  net_revenue_yuan: number;
  revenue_yuan: number;
  provider_cost_yuan: number;
  speech_cost_yuan: number;
  speech_calls: number;
  unknown_cost_calls: number;
  supplier_billed_cost_yuan: number;
  cost_difference_yuan: number;
  reconciliation_coverage_rate: number;
  cost_status: "reconciled" | "partial" | "estimated" | "actual_usage" | "incomplete" | "no_data";
  direct_margin_yuan: number;
  direct_margin_rate: number;
  total_users: number;
  new_users: number;
  active_users: number;
  paid_users: number;
  active_subscriptions: number;
  model_calls: number;
  total_tokens: number;
  credits_consumed: number;
  model_success_rate: number;
}

export interface OverviewDaily {
  date: string;
  label?: string;
  period_start?: string;
  period_end?: string;
  gross_revenue_yuan: number;
  refund_yuan: number;
  net_revenue_yuan: number;
  revenue_yuan: number;
  provider_cost_yuan: number;
  speech_cost_yuan: number;
  speech_calls: number;
  unknown_cost_calls: number;
  supplier_billed_cost_yuan: number;
  direct_margin_yuan: number;
  new_users: number;
  active_users: number;
  paid_users: number;
  model_calls: number;
  total_tokens: number;
}

export interface OverviewDistribution {
  code: string;
  name: string;
  count: number;
  revenue_yuan: number;
}

export interface OverviewModelCost {
  model: string;
  usage_kind: "chat" | "speech";
  duration_ms: number;
  unknown_cost_calls: number;
  calls: number;
  tokens: number;
  cost_yuan: number;
  success_rate: number;
}

export interface OverviewHealth {
  open_tickets: number;
  overdue_tickets: number;
  expiring_subscriptions: number;
  low_credit_users: number;
  available_credits: number;
  pending_credits: number;
  message_delivery_rate: number;
  message_read_rate: number;
  active_model_routes: number;
  provider_finance_accounts: number;
  low_balance_accounts: number;
  finance_sync_failures: number;
}

export interface OverviewRisk {
  code: string;
  title: string;
  description: string;
  severity: "critical" | "warning" | "info";
  count: number;
  action_path?: string;
}

export interface OperationsOverview {
  period_days: number;
  period_preset: OverviewPeriodPreset;
  period_label: string;
  grain: "day" | "week" | "month";
  period_start: string;
  period_end: string;
  generated_at: string;
  summary: OverviewSummary;
  previous: OverviewSummary;
  daily: OverviewDaily[];
  user_funnel: OverviewDistribution[];
  level_distribution: OverviewDistribution[];
  subscription_distribution: OverviewDistribution[];
  model_cost_distribution: OverviewModelCost[];
  health: OverviewHealth;
  risks: OverviewRisk[];
  data_quality: {
    telemetry_events: number;
    latest_telemetry_at?: string;
    latest_model_usage_at?: string;
    latest_supplier_bill_at?: string;
    actual_usage_calls: number;
    estimated_usage_calls: number;
    sources: string[];
  };
}

export type OverviewPeriodPreset =
  | "today"
  | "yesterday"
  | "last_7_days"
  | "last_30_days"
  | "last_90_days"
  | "this_month"
  | "last_month"
  | "this_quarter"
  | "this_year"
  | "custom";

export interface OverviewQuery {
  preset: OverviewPeriodPreset;
  start_date?: string;
  end_date?: string;
  grain?: "day" | "week" | "month";
}

const OperationsOverviewAPI = {
  get: (query: OverviewQuery | 7 | 30 | 90) =>
    request<ApiResponse<OperationsOverview>>({
      url: "/operations/overview",
      method: "get",
      params: typeof query === "number" ? { period_days: query } : query,
    }),
};

export default OperationsOverviewAPI;
