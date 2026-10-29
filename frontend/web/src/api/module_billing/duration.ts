import { request } from "@utils";

export interface DurationAdjustment {
  id: number;
  direction: "grant" | "deduct";
  days: number;
  seconds_delta: number;
  before_expires_at: string | null;
  after_expires_at: string;
  reason: string;
  operator_name: string;
  created_time: string;
}

export interface DurationState {
  status: string;
  expires_at: string | null;
  remaining_seconds: number;
  server_time: string;
  catalog_plan_id: number | null;
  plans: { id: number; name: string }[];
  records: DurationAdjustment[];
}

export interface DurationAdjustForm {
  direction: "grant" | "deduct";
  days: number;
  catalog_plan_id?: number;
  reason: string;
  idempotency_key: string;
  expected_expires_at: string | null;
}

export default {
  state: (userId: number) =>
    request<ApiResponse<DurationState>>({
      url: `/operations/billing/subscriptions/users/${userId}/duration`,
      method: "get",
    }),
  adjust: (userId: number, data: DurationAdjustForm) =>
    request<ApiResponse<DurationAdjustment>>({
      url: `/operations/billing/subscriptions/users/${userId}/duration`,
      method: "post",
      data,
    }),
};
