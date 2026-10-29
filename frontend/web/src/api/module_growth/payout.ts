import { request } from "@utils";
export interface Withdrawal {
  id: number;
  user_id: number;
  provider: string;
  amount_fen: number;
  status: string;
  out_bill_no: string;
  reason: string | null;
  payee: string;
  created_time: string;
  provider_bill_no: string | null;
}
export interface PayoutAttempt {
  id: number;
  action: string;
  status: string;
  detail: string;
  created_time: string;
}
export default {
  syncRefund: (order_no: string, refund_no: string) =>
    request<ApiResponse<{ id: number }>>({
      url: "/growth/refunds/synchronize",
      method: "post",
      data: { order_no, refund_no },
    }),
  list: (page_no: number) =>
    request<ApiResponse<PageResult<Withdrawal>>>({
      url: "/growth/withdrawals",
      method: "get",
      params: { page_no, page_size: 20 },
    }),
  capabilities: () =>
    request<ApiResponse<{ provider: string; available: boolean; reason: string }[]>>({
      url: "/growth/payout/capabilities",
      method: "get",
    }),
  review: (id: number, approved: boolean, reason: string) =>
    request<ApiResponse<Withdrawal>>({
      url: `/growth/withdrawals/${id}/review`,
      method: "post",
      data: { approved, reason },
    }),
  query: (id: number) =>
    request<ApiResponse<{ id: number }>>({
      url: `/growth/withdrawals/${id}/query`,
      method: "post",
    }),
  attempts: (id: number) =>
    request<ApiResponse<PayoutAttempt[]>>({
      url: `/growth/withdrawals/${id}/attempts`,
      method: "get",
    }),
};
