import { describe, expect, it, vi } from "vitest";
import type { Order } from "@/api/module_finance";
import { isUnpaidOrder, orderActions } from "./order-actions";

const unpaid: Order = {
  id: 1,
  order_no: "YXTEST001",
  user_id: 1,
  username: "test",
  display_name: "测试用户",
  provider: "wechat",
  provider_trade_no: null,
  purchase_type: "first",
  product_name: "套餐",
  amount_fen: 100,
  refunded_fen: 0,
  refund_reserved_fen: 0,
  refundable_fen: 0,
  status: "pending",
  refund_status: "none",
  fulfillment_status: "not_paid",
  currency: "CNY",
  created_time: "2026-10-14T00:00:00Z",
  paid_at: null,
  expires_at: "2026-10-14T00:15:00Z",
  closed_at: null,
  failure_reason: null,
};
const handlers = () => ({
  details: vi.fn(),
  verify: vi.fn(),
  close: vi.fn(),
  remove: vi.fn(),
  refund: vi.fn(),
});

describe("交易订单可执行操作", () => {
  it("提供未支付订单的关闭与删除，并使用财务写权限", () => {
    const callbacks = handlers();
    const actions = orderActions(unpaid, callbacks, false);
    expect(actions.map((action) => action.label)).toEqual([
      "详情",
      "核验",
      "关闭订单",
      "删除未支付订单",
    ]);
    actions.find((action) => action.key === "close")!.run();
    expect(callbacks.close).toHaveBeenCalledOnce();
    expect(actions.find((action) => action.key === "delete")?.perm).toBe(
      "workspace:finance:order:query"
    );
  });
  it("已关闭订单仅保留删除，已付款或已履约订单不提供破坏性操作", () => {
    expect(
      orderActions({ ...unpaid, status: "closed" }, handlers(), false).map((action) => action.key)
    ).toEqual(["detail", "query", "delete"]);
    for (const order of [
      { ...unpaid, status: "paid", paid_at: "2026-10-14T00:01:00Z" },
      { ...unpaid, provider_trade_no: "channel-paid" },
      { ...unpaid, fulfillment_status: "fulfilled" },
      { ...unpaid, refund_reserved_fen: 100 },
    ]) {
      expect(isUnpaidOrder(order)).toBe(false);
      expect(orderActions(order, handlers(), false).map((action) => action.key)).not.toContain(
        "delete"
      );
    }
  });
  it("执行中禁用写操作，已付款仍保留合法退款入口", () => {
    expect(
      orderActions(unpaid, handlers(), true)
        .filter((action) => action.key !== "detail")
        .every((action) => action.disabled)
    ).toBe(true);
    expect(
      orderActions(
        { ...unpaid, status: "paid", paid_at: "2026-10-14T00:01:00Z", refundable_fen: 100 },
        handlers(),
        false
      ).map((action) => action.key)
    ).toEqual(["detail", "query", "refund"]);
  });
});
