import { request } from "@utils";

export type RuleKind = "usage" | "promotion" | "rights" | "incentive";
export type Metric =
  | "net_paid_fen"
  | "active_days"
  | "artifacts"
  | "feedback"
  | "registrations"
  | "first_users"
  | "first_payers"
  | "conversion_rate"
  | "retention_rate"
  | "compliance_rate"
  | "refund_rate";
export interface Condition {
  metric: Metric;
  operator: "gte" | "lte";
  value: number;
}
export interface GradePolicy {
  track: "usage" | "promotion";
  window_days: number;
  cadence: "daily" | "weekly" | "monthly";
  downgrade_periods: number;
  retention_min_samples: number;
  compliance_min_coverage: number;
  dimensions: { metric: Metric; weight: number; cap: number }[];
  grades: { code: string; name: string; min_score: number; conditions: Condition[] }[];
}
export interface RightsPolicy {
  credit_valid_days: number;
  gift_enabled: boolean;
  gift_reward_credits: boolean;
  gift_requires_subscription: boolean;
  gift_minimum: number;
  gift_daily_count: number;
  gift_monthly_percent: number;
  withdrawal_enabled: boolean;
  withdrawal_min_fen: number;
  withdrawal_max_fen: number;
  withdrawal_daily_fen: number;
  withdrawal_monthly_fen: number;
  withdrawal_daily_count: number;
}
export interface RewardAction {
  recipient: "actor" | "inviter";
  asset: "credits" | "cash";
  calculation: "fixed" | "paid_percent";
  amount: number;
  percent: number;
  grade_percent: Record<string, number>;
  credits_per_yuan: number;
  maximum: number;
}
export interface IncentivePolicy {
  event:
    | "daily_login"
    | "first_task"
    | "first_subscription"
    | "first_traffic"
    | "feedback"
    | "artifact"
    | "cocreate";
  name: string;
  description: string;
  mode: "auto" | "review" | "simulation";
  feedback_grade: "S" | "A" | "B" | "C" | null;
  usage_grades: string[];
  promotion_grades: string[];
  require_subscription: boolean;
  priority: number;
  stackable: boolean;
  daily_limit: number;
  monthly_limit: number;
  observe_days: number;
  budget_credits: number;
  budget_cash_fen: number;
  actions: RewardAction[];
}
export type Policy = GradePolicy | RightsPolicy | IncentivePolicy;
export interface GrowthRule {
  id: number;
  key: string;
  kind: RuleKind;
  name: string;
  version: number;
  status: "draft" | "published" | "stopped";
  config: Policy;
  effective_at: string | null;
  created_time: string;
  used_credits: number;
  used_cash_fen: number;
}
export interface Evaluation {
  user_id: number;
  name: string;
  old_grade: string;
  new_grade: string;
  score: number;
  reason?: string;
  insufficient: boolean;
  metrics: Record<string, number | null>;
  evaluated_at: string;
  window_days: number;
}
export interface GrowthProfile {
  invite_code: string;
  invite_url: string;
  usage_grade: string;
  promotion_grade: string;
  evaluations: Partial<Record<"usage" | "promotion", Evaluation>>;
  invited_count: number;
  reward_totals: Partial<Record<"credits" | "cash", number>>;
  binding: { eligible: boolean; reason?: string; deadline?: string };
}
export interface Referral {
  id: number;
  user_id: number | null;
  name: string;
  bound_at: string;
  source: string;
  first_task_at: string | null;
  first_paid_at: string | null;
  risk_status: string;
}
export interface AuditRow {
  id: number;
  user_id: number;
  status: string;
  kind?: string;
  name?: string;
  asset?: string;
  amount?: number;
  reason?: string;
  review_reason?: string;
  project_ref?: string;
  artifact_ref?: string;
  completed_at?: string;
  release_at?: string;
  snapshot?: { name: string };
}
export const metricLabels: Record<Metric, string> = {
  net_paid_fen: "净支付（分）",
  active_days: "有效活跃天数",
  artifacts: "有效成果数",
  feedback: "采纳反馈数",
  registrations: "有效注册人数",
  first_users: "首次使用人数",
  first_payers: "首次付费人数",
  conversion_rate: "付费转化率（%）",
  retention_rate: "30日留存率（%）",
  compliance_rate: "合规率（%）",
  refund_rate: "退款率（%）",
};
export const eventLabels: Record<IncentivePolicy["event"], string> = {
  daily_login: "每日登录",
  first_task: "首次有效任务",
  first_subscription: "首次订阅付费",
  first_traffic: "首次流量包付费",
  feedback: "反馈被采纳",
  artifact: "有效成果核验",
  cocreate: "共创审核通过",
};
export default {
  rules: (kind: RuleKind) =>
    request<ApiResponse<GrowthRule[]>>({ url: "/growth/rules", method: "get", params: { kind } }),
  seed: () => request<ApiResponse<GrowthRule[]>>({ url: "/growth/rules/defaults", method: "post" }),
  save: (data: Pick<GrowthRule, "kind" | "key" | "name" | "config">) =>
    request<ApiResponse<GrowthRule>>({ url: "/growth/rules", method: "post", data }),
  saveAndPublish: (data: Pick<GrowthRule, "kind" | "key" | "name" | "config">) =>
    request<ApiResponse<GrowthRule>>({
      url: "/growth/rules/save-and-publish",
      method: "post",
      data,
    }),
  publish: (id: number, effective_at: string) =>
    request<ApiResponse<GrowthRule>>({
      url: `/growth/rules/${id}/publish`,
      method: "post",
      data: { effective_at },
    }),
  stop: (id: number) =>
    request<ApiResponse<GrowthRule>>({ url: `/growth/rules/${id}/stop`, method: "post" }),
  preview: (id: number, page_no = 1) =>
    request<ApiResponse<PageResult<Evaluation>>>({
      url: `/growth/rules/${id}/preview`,
      method: "get",
      params: { page_no, page_size: 20 },
    }),
  evaluate: (id: number) =>
    request<ApiResponse<{ evaluated: number }>>({
      url: `/growth/rules/${id}/evaluate`,
      method: "post",
    }),
  archiveLegacy: (id: number) =>
    request<ApiResponse<{ id: number }>>({
      url: `/growth/legacy-segments/${id}/archive`,
      method: "post",
    }),
  legacy: () =>
    request<ApiResponse<{ id: number; name: string; type: string }[]>>({
      url: "/growth/legacy-references",
      method: "get",
    }),
  profile: (id: number) =>
    request<ApiResponse<GrowthProfile>>({ url: `/growth/users/${id}`, method: "get" }),
  referrals: (id: number, page_no = 1) =>
    request<ApiResponse<PageResult<Referral>>>({
      url: `/growth/users/${id}/referrals`,
      method: "get",
      params: { page_no, page_size: 20 },
    }),
  auditRows: (kind: "rewards" | "tasks" | "events", page_no = 1) =>
    request<ApiResponse<PageResult<AuditRow>>>({
      url: `/growth/${kind}`,
      method: "get",
      params: { page_no, page_size: 20 },
    }),
  review: (
    kind: "rewards" | "tasks" | "referrals",
    id: number,
    approved: boolean,
    reason: string
  ) =>
    request<ApiResponse<AuditRow>>({
      url: `/growth/${kind}/${id}/review`,
      method: "post",
      data: { approved, reason },
    }),
};
