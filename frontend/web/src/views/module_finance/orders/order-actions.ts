import type { Order } from "@/api/module_finance";
import type { TableOperationAction } from "@utils";

interface OrderActionHandlers {
  details: () => void;
  verify: () => void;
  close: () => void;
  remove: () => void;
  refund: () => void;
}

export function isUnpaidOrder(order: Order): boolean {
  return (
    ["created", "pending", "confirming", "failed", "closed"].includes(order.status) &&
    !order.paid_at &&
    !order.provider_trade_no &&
    order.fulfillment_status === "not_paid" &&
    order.refunded_fen === 0 &&
    order.refund_reserved_fen === 0
  );
}

export function orderActions(
  order: Order,
  handlers: OrderActionHandlers,
  busy: boolean
): TableOperationAction[] {
  const actions: TableOperationAction[] = [
    {
      key: "detail",
      label: "详情",
      artType: "custom",
      icon: "ri:file-list-line",
      run: handlers.details,
    },
    {
      key: "query",
      label: "核验",
      artType: "custom",
      icon: "ri:search-line",
      perm: "workspace:finance:order:query",
      disabled: busy,
      run: handlers.verify,
    },
  ];
  if (isUnpaidOrder(order)) {
    if (order.status !== "closed") {
      actions.push({
        key: "close",
        label: "关闭订单",
        artType: "custom",
        icon: "ri:close-circle-line",
        perm: "workspace:finance:order:query",
        disabled: busy,
        run: handlers.close,
      });
    }
    actions.push({
      key: "delete",
      label: "删除未支付订单",
      artType: "delete",
      perm: "workspace:finance:order:query",
      disabled: busy,
      run: handlers.remove,
    });
  }
  if (order.refundable_fen > 0) {
    actions.push({
      key: "refund",
      label: "退款",
      artType: "custom",
      icon: "ri:refund-2-line",
      perm: "workspace:finance:refund:create",
      disabled: busy,
      run: handlers.refund,
    });
  }
  return actions;
}
