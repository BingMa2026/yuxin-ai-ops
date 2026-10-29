import { request } from "@utils";
import type { Withdrawal } from "@/api/module_growth/payout";

export type Provider = "alipay" | "wechat";
export interface FinanceQuery {
  entitlement_kind?: "credits" | "duration";
  mode_switch_status?: string;
  page_no?: number;
  page_size?: number;
  keyword?: string;
  provider?: Provider;
  status?: string;
  purchase_type?: string;
  start_date?: string;
  end_date?: string;
  min_amount_fen?: number;
  max_amount_fen?: number;
  user_id?: number;
  time_field?: "created_time" | "paid_at";
}
export type FinancePage<T> = PageResult<T> & { summary?: Record<string, number> };
export interface Order {
  entitlement_kind?: "credits" | "duration";
  mode_switch?: {
    status: string;
    source_mode?: string | null;
    target_mode: string;
    message?: string;
    result_mode_version?: number;
  } | null;
  id: number;
  order_no: string;
  user_id: number;
  username: string;
  display_name: string;
  provider: Provider;
  provider_trade_no: string | null;
  purchase_type: string;
  product_name: string;
  amount_fen: number;
  refunded_fen: number;
  refund_reserved_fen: number;
  refundable_fen: number;
  status: string;
  refund_status: string;
  fulfillment_status: string;
  currency: string;
  created_time: string;
  paid_at: string | null;
  expires_at: string;
  closed_at: string | null;
  failure_reason: string | null;
}
export interface Audit {
  id: number;
  action: string;
  operator_id: number | null;
  reason: string;
  created_time: string;
  before?: Record<string, unknown>;
  after?: Record<string, unknown>;
}
export interface Refund {
  id: number;
  order_id: number;
  order_no: string;
  user_id: number;
  username: string;
  display_name: string;
  provider: Provider;
  refund_no: string;
  amount_fen: number;
  reason: string;
  status: string;
  entitlement_action: "retain" | "terminate";
  entitlement_result: Record<string, number | string | null> | null;
  requested_by: number;
  reviewed_by: number | null;
  reviewed_at: string | null;
  review_reason: string | null;
  submitted_at: string | null;
  completed_at: string | null;
  next_attempt_at: string | null;
  attempt_count: number;
  provider_refund_no: string | null;
  failure_code: string | null;
  failure_reason: string | null;
  created_time: string;
}
export interface RefundPreview {
  entitlement_kind?: "credits" | "duration";
  action: "retain" | "terminate";
  before: SubscriptionPreview;
  after: SubscriptionPreview;
  revoked_available: number;
  cancelled_pending: number;
  reserved_at_refund: number;
  consumed_or_expired: number;
  superseded_credits?: number;
  cycles_cancelled: number;
  preview_token: string;
}
export interface SubscriptionPreview {
  status: string;
  catalog_plan_id: number | null;
  plan_name: string;
  starts_at: string | null;
  ends_at: string | null;
}
export interface Credit {
  id: number;
  amount: number;
  available: number;
  reserved: number;
  status: string;
  release_at: string;
  expires_at: string;
}
export interface OrderDetail {
  order: Order;
  plan_snapshot: Record<string, unknown>;
  strategy_snapshot: Record<string, unknown>;
  cycles: { id: number; starts_at: string; ends_at: string; status: string }[];
  credits: Credit[];
  attempts: {
    id: number;
    action: string;
    status: string;
    error_message: string | null;
    created_time: string;
    completed_at: string | null;
  }[];
  callbacks: {
    id: number;
    status: string;
    failure_reason: string | null;
    created_time: string;
    verified_at: string | null;
  }[];
  refunds: {
    id: number;
    refund_no: string;
    amount_fen: number;
    reason: string;
    status: string;
    refunded_at: string;
    provider_refund_no: string;
  }[];
  rewards: {
    id: number;
    user_id: number;
    asset: string;
    amount: number;
    reversed_amount: number;
    status: string;
  }[];
  audits: Audit[];
}
export interface Bill {
  id: number;
  provider: Provider;
  bill_date: string;
  status: string;
  requested_by: number;
  file_digest: string | null;
  downloaded_at: string | null;
  completed_at: string | null;
  summary: Record<string, number>;
  error_message: string | null;
  created_time: string;
}
export interface BillEntry {
  id: number;
  bill_id: number;
  order_id: number | null;
  order_no: string;
  provider_trade_no: string | null;
  refund_no: string | null;
  entry_type: string;
  channel_amount_fen: number;
  system_amount_fen: number;
  fee_fen: number | null;
  occurred_at: string | null;
  match_status: string;
  resolution: string | null;
  resolved_by: number | null;
  resolved_at: string | null;
}
export interface Issue {
  id: number;
  kind: string;
  severity: string;
  object_type: string;
  object_id: number;
  order_no: string | null;
  amount_fen: number | null;
  provider: Provider | null;
  status: string;
  detail: string;
  last_seen_at: string;
  assigned_to: number | null;
  resolution: string | null;
  resolved_at: string | null;
  created_time: string;
}
export interface Payout extends Withdrawal {
  username: string;
  display_name: string;
  reviewed_at: string | null;
  completed_at: string | null;
  attempt_count: number;
  next_attempt_at: string | null;
}
export interface Channel {
  id: number;
  provider: Provider;
  name: string;
  enabled: boolean;
  app_enabled: boolean;
  configured: boolean;
  mode: string;
  missing_fields: string[];
  merchant_identity: string | null;
  fee_rate: number;
  settlement_cycle: string;
  payout_enabled: boolean;
  refund_enabled: boolean;
  payout_ready: boolean;
  payout_reason: string;
  certificates: {
    name: string;
    expires_at: string | null;
    days_left: number | null;
    status: string;
  }[];
  checked_at: string;
  last_changed_at: string | null;
}
export interface Metrics {
  received_fen: number;
  refund_fen: number;
  net_received_fen: number;
  payout_fen: number;
  paid_orders: number;
  average_order_fen: number;
}
export interface RefundLedger {
  id: number;
  order_id: number;
  order_no: string;
  user_id: number;
  username: string;
  display_name: string;
  provider: Provider;
  provider_refund_no: string | null;
  refund_no: string;
  amount_fen: number;
  refunded_at: string | null;
  reason: string | null;
  status: string;
}
export interface Overview {
  start_date: string;
  end_date: string;
  generated_at: string;
  current: Metrics;
  previous: Metrics;
  daily: {
    date: string;
    received_fen: number;
    refund_fen: number;
    payout_fen: number;
    paid_orders: number;
  }[];
  channels: {
    provider: Provider;
    received_fen: number;
    paid_orders: number;
    refund_fen: number;
    created_orders: number;
    converted_orders: number;
    conversion_rate: number | null;
  }[];
  tasks: Record<string, number>;
  promotion_balances: { available_fen: number; frozen_fen: number; debt_fen: number };
  reconciliation: {
    completed_days: number;
    failed_days: number;
    difference_count: number;
    verified_fee_fen: number | null;
  };
}
const get = <T>(path: string, params?: FinanceQuery | Record<string, unknown>) =>
  request<ApiResponse<T>>({ url: `/finance/${path}`, method: "get", params });
const post = <T>(path: string, data?: unknown) =>
  request<ApiResponse<T>>({ url: `/finance/${path}`, method: "post", data });
export default {
  overview: (params: { start_date: string; end_date: string }) => get<Overview>("overview", params),
  orders: (params: FinanceQuery) => get<FinancePage<Order>>("orders", params),
  order: (id: number) => get<OrderDetail>(`orders/${id}`),
  queryOrder: (id: number, reason: string) => post<OrderDetail>(`orders/${id}/query`, { reason }),
  closeOrder: (id: number, reason: string) =>
    post<{ status: string }>(`orders/${id}/close`, { reason }),
  deleteOrder: (id: number, reason: string) =>
    request.delete<ApiResponse<{ deleted: boolean; channel_status: string }>>(
      `/finance/orders/${id}`,
      {
        data: { reason },
      }
    ),
  exportOrders: (params: FinanceQuery) =>
    request<Blob>({ url: "/finance/orders/export", method: "get", params, responseType: "blob" }),
  refunds: (params: FinanceQuery) => get<FinancePage<Refund>>("refunds", params),
  refundLedger: (params: FinanceQuery) => get<FinancePage<RefundLedger>>("refund-ledger", params),
  refund: (id: number) => get<{ refund: Refund; audits: Audit[] }>(`refunds/${id}`),
  createRefund: (data: {
    order_id: number;
    amount_fen: number;
    reason: string;
    entitlement_action: "retain" | "terminate";
    idempotency_key: string;
    preview_token?: string;
  }) => post<Refund>("refunds", data),
  refundPreview: (id: number, action: "retain" | "terminate") =>
    get<RefundPreview>(`orders/${id}/refund-preview`, { action }),
  refundReviewPreview: (id: number) => get<RefundPreview>(`refunds/${id}/preview`),
  reviewRefund: (id: number, approved: boolean, reason: string, preview_token?: string) =>
    post<Refund>(`refunds/${id}/review`, { approved, reason, preview_token }),
  queryRefund: (id: number, reason: string) => post<Refund>(`refunds/${id}/query`, { reason }),
  retryRefund: (id: number, reason: string) => post<Refund>(`refunds/${id}/retry`, { reason }),
  syncRefund: (data: { order_no: string; refund_no: string; reason: string }) =>
    post<Record<string, unknown>>("refunds/synchronize", data),
  bills: (params: FinanceQuery) => get<FinancePage<Bill>>("bills", params),
  requestBill: (provider: Provider, bill_date: string) =>
    post<Bill>("bills", { provider, bill_date }),
  requestBillBatch: (provider: Provider, start_date: string, end_date: string) =>
    post<Bill[]>("bills/batch", { provider, start_date, end_date }),
  billAutomation: () =>
    get<{ enabled: boolean; hour: number; timezone: string }>("bill-automation"),
  billEntries: (id: number, params: FinanceQuery) =>
    get<FinancePage<BillEntry>>(`bills/${id}/entries`, params),
  resolveEntry: (id: number, reason: string) =>
    post<BillEntry>(`bill-entries/${id}/resolve`, { reason }),
  issues: (params: FinanceQuery) => get<FinancePage<Issue>>("issues", params),
  refreshIssues: () => post<Record<string, never>>("issues/refresh"),
  issueAction: (id: number, action: "claim" | "resolve" | "reopen", reason: string) =>
    post<Issue>(`issues/${id}/action`, { action, reason }),
  channels: () => get<Channel[]>("channels"),
  updateChannel: (
    provider: Provider,
    data: {
      collection_enabled: boolean;
      payout_enabled: boolean;
      refund_enabled: boolean;
      reason: string;
    }
  ) => request<ApiResponse<Channel>>({ url: `/finance/channels/${provider}`, method: "put", data }),
  payouts: (params: FinanceQuery) => get<FinancePage<Payout>>("withdrawals", params),
};
