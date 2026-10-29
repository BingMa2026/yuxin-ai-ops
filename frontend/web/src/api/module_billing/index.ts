import { request } from "@utils";

export interface ReleaseItem {
  offset_day: number;
  amount: number;
  account_type:
    | "activity_reward"
    | "current_cycle"
    | "monthly_reserve"
    | "traffic_pack"
    | "enterprise_pool"
    | "manual";
}
export interface PricingTemplate extends BaseType {
  entitlement_kind?: "credits" | "duration";
  version_id: number;
  code: string;
  name: string;
  plan_type: "subscription" | "credit_pack";
  tier_code?: "free" | "starter" | "professional" | "enterprise";
  tier_order: number;
  billing_period_days: number;
  one_time_price_fen: number;
  recurring_price_fen: number;
  total_credits: number;
  release_plan: ReleaseItem[];
  credit_valid_days: number;
  renewal_rule?: string;
  benefits: string[];
  requires_active_subscription: boolean;
  status: string;
  order: number;
}
export interface PricingVersion extends BaseType {
  version: string;
  name: string;
  status: string;
  effective_at?: string;
  published_at?: string;
  credit_unit_name: string;
  margin_baseline: number;
  credits_per_yuan: number;
  subscription_cycle_days: number;
  renewal_discount_rate: number;
  margin_floor: number;
  account_priority: string[];
  description?: string;
  template_count: number;
}
export interface PricingVersionForm {
  version: string;
  name: string;
  effective_at?: string;
  margin_baseline: number;
  credits_per_yuan: number;
  subscription_cycle_days: number;
  renewal_discount_rate: number;
  margin_floor: number;
  account_priority: string[];
  description?: string;
  templates: Omit<PricingTemplate, keyof BaseType | "version_id" | "status">[];
}
export interface CatalogPlan extends BaseType {
  entitlement_kind?: "credits" | "duration";
  app_id: number;
  template_id?: number;
  pricing_version_id: number;
  code: string;
  name: string;
  plan_type: "subscription" | "credit_pack";
  tier_code?: "free" | "starter" | "professional" | "enterprise";
  tier_order: number;
  one_time_price_fen: number;
  recurring_price_fen: number;
  benefit_period_days: number;
  total_credits: number;
  release_plan: ReleaseItem[];
  credit_valid_days: number;
  benefits: string[];
  requires_active_subscription: boolean;
  cost_budget_yuan?: number;
  effective_from?: string;
  effective_until?: string;
  order: number;
  status: "draft" | "on_sale" | "off_sale";
  effective_price_fen?: number;
  base_price_fen?: number;
  discount_amount_fen?: number;
  purchase_type?: "first" | "renewal";
  strategy_name?: string;
  strategy_version?: string;
  is_current?: boolean;
  eligible?: boolean;
  disabled_reason?: string;
}
export type CatalogPlanForm = Omit<
  CatalogPlan,
  keyof BaseType | "app_id" | "effective_price_fen" | "strategy_version"
>;
export interface PricingStrategy extends BaseType {
  app_id: number;
  version?: string;
  pricing_version_id?: number;
  catalog_plan_id: number;
  name: string;
  purchase_type: "first" | "renewal" | "all";
  discount_rate?: number;
  fixed_price_fen?: number;
  starts_at: string;
  ends_at: string;
  status: "active" | "inactive";
  description?: string;
  scope_type: "all" | "new" | "level" | "segment" | "users";
  scope_value: Record<string, unknown>;
  published_at?: string;
  items: PricingStrategyItem[];
}
export interface PricingStrategyItem {
  id?: number;
  catalog_plan_id: number;
  purchase_type: "first" | "renewal" | "all";
  discount_rate: number;
  margin_rate: number;
  execution_price_fen?: number;
  allowed_cost_yuan?: number;
  credits_per_cost_yuan?: number;
  remark?: string;
}
export interface PricingStrategyForm {
  catalog_plan_id: number;
  name: string;
  version?: string;
  pricing_version_id?: number;
  scope_type: PricingStrategy["scope_type"];
  scope_value: Record<string, unknown>;
  purchase_type: PricingStrategy["purchase_type"];
  starts_at: string;
  ends_at: string;
  status: "active" | "inactive";
  description?: string;
  items: PricingStrategyItem[];
}
export interface PaymentOrder extends BaseType {
  app_id: number;
  user_id: number;
  order_no: string;
  catalog_plan_id: number;
  purchase_type: string;
  provider: string;
  amount_fen: number;
  currency: string;
  plan_snapshot: Record<string, unknown>;
  strategy_snapshot?: Record<string, unknown>;
  status: string;
  pay_url?: string;
  expires_at: string;
  paid_at?: string;
  auto_renew_requested: boolean;
}
export interface SubscriptionInfo extends BaseType {
  entitlement_kind?: "credits" | "duration";
  app_id: number;
  user_id: number;
  username: string;
  display_name?: string;
  catalog_plan_id: number;
  plan_name: string;
  status: string;
  auto_renew: boolean;
  current_period_start: string;
  current_period_end: string;
  next_renewal_at?: string;
  available_credits: number;
  pending_credits: number;
}

const BillingAPI = {
  preview: (params: { user_id?: number; purchase_type?: "first" | "renewal" }) =>
    request<ApiResponse<CatalogPlan[]>>({
      url: "/operations/billing/pricing/preview",
      method: "get",
      params,
    }),
  versions: () =>
    request<ApiResponse<PricingVersion[]>>({
      url: "/operations/billing/pricing/versions",
      method: "get",
    }),
  createVersion: (data: PricingVersionForm) =>
    request<ApiResponse<PricingVersion>>({
      url: "/operations/billing/pricing/versions",
      method: "post",
      data,
    }),
  updateVersion: (id: number, data: PricingVersionForm) =>
    request<ApiResponse<PricingVersion>>({
      url: `/operations/billing/pricing/versions/${id}`,
      method: "put",
      data,
    }),
  deleteVersion: (id: number) =>
    request<ApiResponse<null>>({
      url: `/operations/billing/pricing/versions/${id}`,
      method: "delete",
    }),
  templates: (versionId: number) =>
    request<ApiResponse<PricingTemplate[]>>({
      url: `/operations/billing/pricing/versions/${versionId}/templates`,
      method: "get",
    }),
  publishVersion: (versionId: number) =>
    request<ApiResponse<PricingVersion>>({
      url: `/operations/billing/pricing/versions/${versionId}/publish`,
      method: "post",
    }),
  plans: (entitlement_kind?: "credits" | "duration") =>
    request<ApiResponse<CatalogPlan[]>>({
      url: "/operations/billing/catalog/plans",
      params: { entitlement_kind },
      method: "get",
    }),
  createPlan: (data: CatalogPlanForm) =>
    request<ApiResponse<CatalogPlan>>({
      url: "/operations/billing/catalog/plans",
      method: "post",
      data,
    }),
  updatePlan: (id: number, data: Partial<CatalogPlanForm>) =>
    request<ApiResponse<CatalogPlan>>({
      url: `/operations/billing/catalog/plans/${id}`,
      method: "patch",
      data,
    }),
  strategies: () =>
    request<ApiResponse<PricingStrategy[]>>({
      url: "/operations/billing/catalog/strategies",
      method: "get",
    }),
  createStrategy: (data: PricingStrategyForm) =>
    request<ApiResponse<PricingStrategy>>({
      url: "/operations/billing/catalog/strategies",
      method: "post",
      data,
    }),
  setStrategyStatus: (id: number, status: PricingStrategy["status"]) =>
    request<ApiResponse<PricingStrategy>>({
      url: `/operations/billing/catalog/strategies/${id}/status`,
      method: "patch",
      data: { status },
    }),
  strategy: (id: number) =>
    request<ApiResponse<PricingStrategy>>({
      url: `/operations/billing/catalog/strategies/${id}`,
      method: "get",
    }),
  updateStrategy: (id: number, data: PricingStrategyForm) =>
    request<ApiResponse<PricingStrategy>>({
      url: `/operations/billing/catalog/strategies/${id}`,
      method: "put",
      data,
    }),
  deleteStrategy: (id: number) =>
    request<ApiResponse<null>>({
      url: `/operations/billing/catalog/strategies/${id}`,
      method: "delete",
    }),
  orders: (entitlement_kind?: "credits" | "duration") =>
    request<ApiResponse<PaymentOrder[]>>({
      url: "/payment/orders",
      method: "get",
      params: { entitlement_kind },
    }),
  subscriptions: (entitlement_kind?: "credits" | "duration") =>
    request<ApiResponse<SubscriptionInfo[]>>({
      url: "/operations/billing/subscriptions",
      params: { entitlement_kind },
      method: "get",
    }),
  setSubscriptionStatus: (id: number, status: string, reason: string) =>
    request<ApiResponse<SubscriptionInfo>>({
      url: `/operations/billing/subscriptions/${id}/status`,
      method: "patch",
      data: { status, reason },
    }),
};

export default BillingAPI;
