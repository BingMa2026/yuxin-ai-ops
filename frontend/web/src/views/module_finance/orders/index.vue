<script setup lang="ts">
import { billingModeLabel, modeSwitchLabel } from "@/api/module_client/app";
import FinanceSearchBar from "@/views/module_finance/components/FinanceSearchBar.vue";
import { ref, watch } from "vue";
import { useRoute } from "vue-router";
import { resolveStatusColumns, renderTableOperationCell } from "@utils";
import API, { type Order } from "@/api/module_finance";
import FaTableHeader from "@/components/tables/fa-table-header/index.vue";
import {
  dateTime,
  money,
  providerName,
  reasonPrompt,
  refundStates,
  searchFields,
  states,
  useFinanceList,
} from "../shared";
import OrderDrawer from "../components/OrderDrawer.vue";
import RefundForm from "../components/RefundForm.vue";
import { orderActions } from "./order-actions";
const route = useRoute();
const {
  currentApp,
  rows,
  total,
  summary,
  loading,
  failed,
  busy,
  query,
  params,
  pagination,
  showSearchBar,
  load,
  search,
  reset,
  changePage,
  changeSize,
} = useFinanceList(API.orders, {
  keyword: String(route.query.keyword || ""),
  status: String(route.query.status || ""),
  start_date: route.query.start_date as string | undefined,
  end_date: route.query.end_date as string | undefined,
  time_field: route.query.time_field === "paid_at" ? "paid_at" : "created_time",
});
const drawer = ref(false),
  orderId = ref<number | null>(null),
  refundOpen = ref(false),
  selected = ref<Order | null>(null);
const searchItems = searchFields([
  "pending",
  "confirming",
  "paid",
  "closed",
  "failed",
  "partially_refunded",
  "refunded",
  "unfulfilled",
]);
searchItems.push({
  label: "时间口径",
  key: "time_field",
  type: "select",
  props: {
    options: [
      { label: "下单时间", value: "created_time" },
      { label: "支付时间", value: "paid_at" },
    ],
  },
  span: 8,
});
searchItems.push(
  {
    label: "权益类型",
    key: "entitlement_kind",
    type: "select",
    props: {
      clearable: true,
      options: [
        { label: "含 token 费用", value: "credits" },
        { label: "token 自费", value: "duration" },
      ],
    },
    span: 8,
  },
  {
    label: "切换状态",
    key: "mode_switch_status",
    type: "select",
    props: {
      clearable: true,
      options: [
        "pending_payment",
        "processing",
        "completed",
        "requires_confirmation",
        "failed",
        "cancelled",
      ].map((value) => ({ value, label: modeSwitchLabel(value) })),
    },
    span: 8,
  }
);
function details(row: Order) {
  orderId.value = row.id;
  drawer.value = true;
}
const { columnChecks, columns } = useTableColumns<Order>(
  resolveStatusColumns<Order>(() => [
    { prop: "order_no", label: "商户订单号", minWidth: 225, showOverflowTooltip: true },
    {
      prop: "display_name",
      label: "用户",
      minWidth: 150,
      formatter: (r) => `${r.display_name || r.username} (#${r.user_id})`,
      showOverflowTooltip: true,
    },
    {
      prop: "entitlement_kind",
      label: "权益类型",
      width: 140,
      formatter: (r) => billingModeLabel(r.entitlement_kind ?? "credits"),
    },
    {
      prop: "mode_switch",
      label: "切换状态",
      width: 110,
      formatter: (r) => modeSwitchLabel(r.mode_switch?.status),
    },
    { prop: "product_name", label: "商品", minWidth: 140, showOverflowTooltip: true },
    { prop: "provider", label: "支付渠道", width: 105, formatter: (r) => providerName(r.provider) },
    { prop: "provider_trade_no", label: "渠道交易号", minWidth: 225, showOverflowTooltip: true },
    {
      prop: "amount_fen",
      label: "订单金额",
      width: 135,
      align: "right",
      formatter: (r) => money(r.amount_fen),
    },
    {
      prop: "refunded_fen",
      label: "累计退款",
      width: 130,
      align: "right",
      formatter: (r) => money(r.refunded_fen),
    },
    {
      prop: "refund_reserved_fen",
      label: "退款占用",
      width: 130,
      align: "right",
      formatter: (r) => money(r.refund_reserved_fen),
    },
    { prop: "status", label: "支付状态", width: 110, status: states },
    { prop: "refund_status", label: "退款状态", width: 110, status: refundStates },
    {
      prop: "fulfillment_status",
      label: "权益状态",
      width: 120,
      status: {
        not_paid: { type: "info", text: "未支付" },
        fulfilled: { type: "success", text: "已发放" },
        missing: { type: "danger", text: "未到账" },
        revoked: { type: "info", text: "退款终止" },
      },
    },
    {
      prop: "created_time",
      label: "下单时间",
      minWidth: 175,
      formatter: (r) => dateTime(r.created_time),
    },
    { prop: "paid_at", label: "支付时间", minWidth: 175, formatter: (r) => dateTime(r.paid_at) },
    {
      prop: "operation",
      label: "操作",
      width: 165,
      fixed: "right",
      formatter: (r) =>
        renderTableOperationCell(
          orderActions(
            r,
            {
              details: () => details(r),
              verify: () => void verify(r),
              close: () => void changeUnpaidOrder(r, "close"),
              remove: () => void changeUnpaidOrder(r, "delete"),
              refund: () => {
                selected.value = r;
                refundOpen.value = true;
              },
            },
            busy.value
          )
        ),
    },
  ])
);
async function verify(row: Order) {
  if (busy.value) return;
  const scope = currentApp.value?.id;
  const reason = await reasonPrompt(
    `向${providerName(row.provider)}核验订单 ${row.order_no}，金额 ${money(row.amount_fen)}。若渠道确认已支付且权益完全未发放，会按原订单快照补发；已有退款或退款申请的订单不补发。`,
    "核验渠道订单"
  );
  if (!reason || scope !== currentApp.value?.id) return;
  busy.value = true;
  try {
    await API.queryOrder(row.id, reason);
    if (scope === currentApp.value?.id) await load();
  } finally {
    busy.value = false;
  }
}
async function exportRows() {
  if (busy.value) return;
  busy.value = true;
  const scope = currentApp.value?.id;
  try {
    const response = await API.exportOrders(params());
    if (scope !== currentApp.value?.id) return;
    const url = URL.createObjectURL(response.data);
    const a = document.createElement("a");
    a.href = url;
    a.download = "交易订单.csv";
    a.click();
    URL.revokeObjectURL(url);
  } finally {
    busy.value = false;
  }
}
async function changeUnpaidOrder(row: Order, action: "close" | "delete") {
  if (busy.value) return;
  const scope = currentApp.value?.id;
  const deleting = action === "delete";
  const reason = await reasonPrompt(
    deleting
      ? `删除未支付订单 ${row.order_no}，金额 ${money(row.amount_fen)}，并清理未入账关联记录。删除后不再出现在订单列表；若渠道后续确认真实付款，原订单会恢复供财务核对。已付款、已发放权益或涉及退款的订单不能删除。`
      : `关闭订单 ${row.order_no}，金额 ${money(row.amount_fen)}。仅关闭未支付订单；渠道结果未明确时继续核对，已付款订单不退款。`,
    deleting ? "删除未支付订单" : "关闭订单"
  );
  if (!reason || busy.value || scope !== currentApp.value?.id) return;
  busy.value = true;
  try {
    if (deleting) await API.deleteOrder(row.id, reason);
    else await API.closeOrder(row.id, reason);
  } finally {
    try {
      if (scope === currentApp.value?.id) {
        if (deleting && orderId.value === row.id) drawer.value = false;
        await load();
      }
    } finally {
      busy.value = false;
    }
  }
}
watch(
  () => currentApp.value?.id,
  () => {
    drawer.value = false;
    refundOpen.value = false;
    selected.value = null;
  }
);
</script>
<template>
  <main class="fa-full-height">
    <template v-if="currentApp"
      ><FinanceSearchBar
        v-show="showSearchBar"
        :model-value="query"
        :items="searchItems"
        :is-expand="false"
        :show-expand="true"
        @update:model-value="Object.assign(query, $event)"
        @search="search"
        @reset="reset" />
      <ElCard class="fa-table-card" :style="{ marginTop: showSearchBar ? '12px' : '0' }"
        ><FaTableHeader
          v-model:columns="columnChecks"
          v-model:showSearchBar="showSearchBar"
          :loading="loading"
          @refresh="load"
          ><template #left
            ><ElButton
              v-hasPerm="['workspace:finance:order:export']"
              :loading="busy"
              @click="exportRows"
              ><FaSvgIcon icon="ri:download-2-line" />导出筛选结果</ElButton
            ><span class="finance-summary"
              >{{ total }} 笔 · 订单 {{ money(summary.amount_fen || 0) }} · 已退
              {{ money(summary.refunded_fen || 0) }}</span
            ></template
          ></FaTableHeader
        >
        <ElAlert
          v-if="failed"
          title="交易订单加载失败，请重试"
          type="error"
          :closable="false" /><FaTable
          :loading="loading"
          :data="rows"
          :columns="columns"
          :pagination="pagination"
          @pagination:current-change="changePage"
          @pagination:size-change="changeSize" /></ElCard
    ></template>
    <ElCard v-else class="fa-table-card"><ElEmpty description="请先选择客户端" /></ElCard>
    <OrderDrawer v-model="drawer" :order-id="orderId" /><RefundForm
      v-model="refundOpen"
      :order="selected"
      @saved="load"
    />
  </main>
</template>
<style scoped>
.finance-summary {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  margin-left: 12px;
}
</style>
