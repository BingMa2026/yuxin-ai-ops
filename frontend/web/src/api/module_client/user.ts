import { request } from "@utils";

export type ClientUserStatus = "active" | "disabled";

export interface ClientUserTag extends BaseType {
  app_id: number;
  user_id: number;
  name: string;
  color?: string;
  status: string;
}

export interface ClientUserInfo extends BaseType {
  app_id: number;
  username: string;
  display_name?: string;
  avatar?: string;
  company_name?: string;
  mobile?: string;
  email?: string;
  status: ClientUserStatus;
  must_change_password: boolean;
  registration_source: string;
  registered_at: string;
  last_login_at?: string;
  last_active_at?: string;
  description?: string;
  tags: ClientUserTag[];
  current_subscription?: string;
  subscription_status?: string;
  subscription_expires_at?: string;
  available_credits: number;
  pending_credits: number;
  total_paid_fen: number;
  model_calls: number;
  token_usage: number;
  credit_usage: number;
  failed_calls: number;
  level_code: "LV1" | "LV2" | "LV3" | "LV4" | "LV5";
  usage_grade: "R1" | "R2" | "R3";
  promotion_grade: "ungraded" | "A1" | "A2" | "A3";
  level_score: number;
  level_evaluated_at?: string;
  level_metrics: Record<string, number>;
}

export interface ClientUserQuery extends PageQuery {
  keyword?: string;
  status?: ClientUserStatus;
  segment?: string;
  registered_at?: string[];
  last_active_at?: string[];
  subscription_status?: string;
  catalog_plan_id?: number;
  min_credits?: number;
  max_credits?: number;
  tag?: string;
  level_code?: ClientUserInfo["level_code"];
  usage_grade?: "R1" | "R2" | "R3";
  promotion_grade?: "ungraded" | "A1" | "A2" | "A3";
  segment_id?: number;
}

export interface ClientUserActivity {
  active_billing_mode?: "credits" | "duration" | null;
  mode_version?: number;
  subscription?: {
    id: number;
    plan_name?: string;
    status: string;
    auto_renew: boolean;
    current_period_start: string;
    current_period_end: string;
  };
  subscription_cycles: {
    cycle_no: number;
    plan_name?: string;
    starts_at: string;
    ends_at: string;
    status: string;
  }[];
  orders: {
    order_no: string;
    plan_name?: string;
    amount_fen: number;
    provider: string;
    status: string;
    created_time: string;
  }[];
  credit_ledger: {
    id: number;
    entry_type: string;
    amount: number;
    balance_after: number;
    reason?: string;
    created_time: string;
  }[];
  model_usage: {
    request_id: string;
    business_code: string;
    provider_model_id?: string;
    input_tokens: number;
    output_tokens: number;
    charged_credits: number;
    provider_cost_yuan: number;
    cost_precision: "actual_usage" | "estimated_usage";
    reconciliation_status: "unreconciled" | "reconciled";
    usage_detail: Record<string, number>;
    latency_ms: number;
    status: string;
    created_time: string;
  }[];
  security_events: {
    action: string;
    success: boolean;
    failure_reason?: string;
    request_ip?: string;
    user_agent?: string;
    created_time: string;
  }[];
  expiring_credits: number;
  project_count: number;
  generated_at: string;
  risk_flags: { code: string; level: string; label: string }[];
  support_tickets: {
    id: number;
    ticket_no: string;
    kind: string;
    category: string;
    subject: string;
    priority: string;
    status: string;
    adopted: boolean;
    created_time: string;
  }[];
  activity_trend: {
    date: string;
    calls: number;
    tokens: number;
    credits: number;
    provider_cost_yuan: number;
    unknown_cost_calls: number;
    events: number;
    logins: number;
  }[];
}

export interface UserLevelConfig extends BaseType {
  app_id: number;
  version: number;
  rules: {
    dimensions: {
      key: string;
      label: string;
      weight: number;
      cap: number;
      unit?: string;
      window?: string;
      description?: string;
    }[];
    levels: {
      code: string;
      name: string;
      min_score: number;
      description?: string;
      service_strategy?: string;
    }[];
  };
  status: string;
}

export interface UserSegment extends BaseType {
  app_id: number;
  name: string;
  description?: string;
  filters: Record<string, unknown>;
  status: string;
  matched_count: number;
}

export interface CreditAccountInfo {
  available: number;
  reserved: number;
  pending: number;
  total_granted: number;
  total_consumed: number;
}

const ClientUserAPI = {
  list(query: ClientUserQuery) {
    return request<ApiResponse<PageResult<ClientUserInfo>>>({
      url: "/operations/client-users/list",
      method: "get",
      params: query,
    });
  },
  detail(id: number) {
    return request<ApiResponse<ClientUserInfo>>({
      url: `/operations/client-users/${id}`,
      method: "get",
    });
  },
  activity(id: number) {
    return request<ApiResponse<ClientUserActivity>>({
      url: `/operations/client-users/${id}/activity`,
      method: "get",
    });
  },
  update(id: number, body: Partial<ClientUserInfo>) {
    return request<ApiResponse<ClientUserInfo>>({
      url: `/operations/client-users/${id}`,
      method: "patch",
      data: body,
    });
  },
  setStatus(id: number, status: ClientUserStatus, reason: string) {
    return request<ApiResponse<ClientUserInfo>>({
      url: `/operations/client-users/${id}/status`,
      method: "patch",
      data: { status, reason },
    });
  },
  temporaryPassword(id: number) {
    return request<ApiResponse<{ temporary_password: string; must_change_password: boolean }>>({
      url: `/operations/client-users/${id}/temporary-password`,
      method: "post",
    });
  },
  adjustCredits(
    id: number,
    body: { amount: number; reason: string; expires_in_days: number; idempotency_key: string }
  ) {
    return request<ApiResponse<CreditAccountInfo>>({
      url: `/operations/billing/catalog/users/${id}/credits`,
      method: "post",
      data: body,
    });
  },
  addTag(id: number, name: string, color?: string) {
    return request<ApiResponse<ClientUserTag>>({
      url: `/operations/client-users/${id}/tags`,
      method: "post",
      data: { name, color },
    });
  },
  removeTag(userId: number, tagId: number) {
    return request<ApiResponse>({
      url: `/operations/client-users/${userId}/tags/${tagId}`,
      method: "delete",
    });
  },
  levelConfig: () =>
    request<ApiResponse<UserLevelConfig>>({
      url: "/operations/client-user-operations/levels/config/current",
      method: "get",
    }),
  saveLevelConfig: (body: UserLevelConfig["rules"]) =>
    request<ApiResponse<UserLevelConfig>>({
      url: "/operations/client-user-operations/levels/config/current",
      method: "put",
      data: body,
    }),
  recalculateLevels: () =>
    request<ApiResponse<number>>({
      url: "/operations/client-user-operations/levels/recalculate",
      method: "post",
    }),
  segments: () =>
    request<ApiResponse<UserSegment[]>>({
      url: "/operations/client-user-operations/segments/saved",
      method: "get",
    }),
  createSegment: (body: Pick<UserSegment, "name" | "description" | "filters">) =>
    request<ApiResponse<UserSegment>>({
      url: "/operations/client-user-operations/segments/saved",
      method: "post",
      data: body,
    }),
};

export default ClientUserAPI;
