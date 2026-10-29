<template>
  <main class="ops-page fa-full-height">
    <FaSearchBar
      v-if="currentApp"
      v-show="showSearchBar"
      :model-value="query"
      :items="searchItems"
      :is-expand="false"
      :show-expand="false"
      @update:model-value="Object.assign(query, $event)"
      @search="handleSearch"
      @reset="handleReset"
    />
    <ElCard
      v-if="currentApp"
      class="fa-table-card"
      :style="{ 'margin-top': showSearchBar ? '12px' : '0' }"
    >
      <ElRadioGroup
        v-model="typeFilter"
        class="mb-4"
        @change="
          pageNo = 1;
          load();
        "
      >
        <ElRadioButton value="">全部类型</ElRadioButton>
        <ElRadioButton value="credits">含 token 费用</ElRadioButton>
        <ElRadioButton value="duration">token 自费</ElRadioButton>
      </ElRadioGroup>
      <ElTabs v-model="tab" @tab-change="resetPage">
        <ElTabPane label="订阅账户" name="subscriptions">
          <FaTableHeader
            v-model:columns="subscriptionColumnChecks"
            v-model:showSearchBar="showSearchBar"
            :loading="loading"
            @refresh="load"
          />
          <FaTable
            :loading="loading"
            :data="subscriptionPageRows"
            :columns="subscriptionColumns"
            :pagination="subscriptionPagination"
            @pagination:size-change="handleSizeChange"
            @pagination:current-change="handleCurrentChange"
          />
        </ElTabPane>
        <ElTabPane label="支付订单" name="orders">
          <FaTableHeader
            v-model:columns="orderColumnChecks"
            v-model:showSearchBar="showSearchBar"
            :loading="loading"
            @refresh="load"
          />
          <FaTable
            :loading="loading"
            :data="orderPageRows"
            :columns="orderColumns"
            :pagination="orderPagination"
            @pagination:size-change="handleSizeChange"
            @pagination:current-change="handleCurrentChange"
          />
        </ElTabPane>
      </ElTabs>
    </ElCard>
    <ElCard v-else class="fa-table-card"><ElEmpty description="请先在顶栏选择客户端" /></ElCard>
  </main>
</template>

<script setup lang="ts">
import { billingModeLabel, type BillingMode } from "@/api/module_client/app";
import { ElMessage, ElMessageBox } from "element-plus";
import BillingAPI, { type PaymentOrder, type SubscriptionInfo } from "@/api/module_billing";
import type { SearchFormItem } from "@/components/forms/fa-search-bar/index.vue";
import FaTableHeader from "@/components/tables/fa-table-header/index.vue";
import { useClientAppStore } from "@stores";
import { renderTableOperationCell, type TableOperationAction } from "@utils";

defineOptions({ name: "BudgetSubscriptions" });

const { currentApp } = storeToRefs(useClientAppStore());
const tab = ref<"subscriptions" | "orders">("subscriptions");
const subscriptions = ref<SubscriptionInfo[]>([]);
const orders = ref<PaymentOrder[]>([]);
const typeFilter = ref<BillingMode | "">("");
const query = reactive({ keyword: "", status: "" });
const submittedQuery = ref({ keyword: "", status: "" });
const pageNo = ref(1);
const pageSize = ref(10);
const showSearchBar = ref(true);
const loading = ref(false);

const planSnapshotName = (value: Record<string, unknown>) => String(value?.name || "—");
const subscriptionStatusName = (status: string) =>
  ({ active: "有效", expired: "已到期", cancelled: "已取消" })[status] || status;
const searchItems = computed<SearchFormItem[]>(() => [
  {
    label: tab.value === "subscriptions" ? "用户" : "订单号",
    key: "keyword",
    type: "input",
    placeholder: tab.value === "subscriptions" ? "请输入账号或姓名" : "请输入订单号",
    clearable: true,
    span: 8,
  },
  {
    label: "状态",
    key: "status",
    type: "select",
    props: {
      placeholder: "请选择状态",
      clearable: true,
      options:
        tab.value === "subscriptions"
          ? [
              { label: "有效", value: "active" },
              { label: "已到期", value: "expired" },
              { label: "已取消", value: "cancelled" },
            ]
          : [
              { label: "待支付", value: "pending" },
              { label: "已支付", value: "paid" },
              { label: "已关闭", value: "closed" },
            ],
    },
    span: 8,
  },
]);

const filteredSubscriptions = computed(() => {
  const keyword = submittedQuery.value.keyword.trim().toLowerCase();
  return subscriptions.value.filter(
    (row) =>
      (!keyword ||
        row.username.toLowerCase().includes(keyword) ||
        (row.display_name || "").toLowerCase().includes(keyword)) &&
      (!submittedQuery.value.status || row.status === submittedQuery.value.status)
  );
});
const filteredOrders = computed(() => {
  const keyword = submittedQuery.value.keyword.trim().toLowerCase();
  return orders.value.filter(
    (row) =>
      (!keyword || row.order_no.toLowerCase().includes(keyword)) &&
      (!submittedQuery.value.status || row.status === submittedQuery.value.status)
  );
});
const subscriptionPageRows = computed(() => {
  const start = (pageNo.value - 1) * pageSize.value;
  return filteredSubscriptions.value.slice(start, start + pageSize.value);
});
const orderPageRows = computed(() => {
  const start = (pageNo.value - 1) * pageSize.value;
  return filteredOrders.value.slice(start, start + pageSize.value);
});
const subscriptionPagination = computed(() => ({
  current: pageNo.value,
  size: pageSize.value,
  total: filteredSubscriptions.value.length,
}));
const orderPagination = computed(() => ({
  current: pageNo.value,
  size: pageSize.value,
  total: filteredOrders.value.length,
}));

function subscriptionActions(row: SubscriptionInfo): TableOperationAction[] {
  return [
    {
      key: "active",
      label: "设为有效",
      artType: "custom",
      icon: "ri:checkbox-circle-line",
      color: "var(--el-color-success)",
      perm: "workspace:budget:subscription:update",
      run: () => void changeSubscriptionStatus(row, "active"),
    },
    {
      key: "expired",
      label: "设为到期",
      artType: "custom",
      icon: "ri:time-line",
      color: "var(--el-color-warning)",
      perm: "workspace:budget:subscription:update",
      run: () => void changeSubscriptionStatus(row, "expired"),
    },
    {
      key: "cancelled",
      label: "设为取消",
      artType: "custom",
      icon: "ri:close-circle-line",
      color: "var(--el-color-danger)",
      perm: "workspace:budget:subscription:update",
      run: () => void changeSubscriptionStatus(row, "cancelled"),
    },
  ].filter((action) => action.key !== row.status) as TableOperationAction[];
}

const { columnChecks: subscriptionColumnChecks, columns: subscriptionColumns } =
  useTableColumns<SubscriptionInfo>(() => [
    { type: "globalIndex", width: 56, label: "序号" },
    { prop: "username", label: "用户账号", minWidth: 140, showOverflowTooltip: true },
    {
      prop: "display_name",
      label: "姓名",
      minWidth: 120,
      formatter: (row: SubscriptionInfo) => row.display_name || "—",
    },
    { prop: "plan_name", label: "当前套餐", minWidth: 130, showOverflowTooltip: true },
    { prop: "current_period_start", label: "开始时间", width: 168, sortable: true },
    { prop: "current_period_end", label: "到期时间", width: 168, sortable: true },
    {
      prop: "entitlement_kind",
      label: "权益类型",
      width: 140,
      formatter: (row: SubscriptionInfo) => billingModeLabel(row.entitlement_kind ?? "credits"),
    },
    {
      prop: "available_credits",
      label: "可用积分",
      width: 110,
      formatter: (row: SubscriptionInfo) =>
        row.entitlement_kind === "duration" ? "—" : row.available_credits.toLocaleString(),
    },
    {
      prop: "pending_credits",
      label: "待释放积分",
      width: 110,
      formatter: (row: SubscriptionInfo) =>
        row.entitlement_kind === "duration" ? "—" : row.pending_credits.toLocaleString(),
    },
    {
      prop: "auto_renew",
      label: "续费方式",
      width: 100,
      formatter: (row: SubscriptionInfo) => (row.auto_renew ? "自动续费" : "手动续费"),
    },
    {
      prop: "status",
      label: "状态",
      width: 88,
      status: {
        active: { type: "success", text: "有效" },
        expired: { type: "warning", text: "已到期" },
        cancelled: { type: "info", text: "已取消" },
      },
    },
    {
      prop: "operation",
      label: "操作",
      width: 110,
      fixed: "right",
      align: "center",
      formatter: (row: SubscriptionInfo) =>
        renderTableOperationCell(subscriptionActions(row), { maxInline: 0 }),
    },
  ]);

const { columnChecks: orderColumnChecks, columns: orderColumns } = useTableColumns<PaymentOrder>(
  () => [
    { type: "globalIndex", width: 56, label: "序号" },
    { prop: "order_no", label: "订单号", minWidth: 220, showOverflowTooltip: true },
    {
      prop: "plan_snapshot",
      label: "套餐快照",
      minWidth: 140,
      formatter: (row: PaymentOrder) =>
        `${planSnapshotName(row.plan_snapshot)}${row.plan_snapshot.entitlement_kind === "duration" ? ` · ${row.plan_snapshot.benefit_period_days}天` : ""}`,
    },
    {
      prop: "amount_fen",
      label: "金额",
      width: 110,
      formatter: (row: PaymentOrder) => `¥${(row.amount_fen / 100).toFixed(2)}`,
    },
    { prop: "provider", label: "支付渠道", width: 110 },
    { prop: "purchase_type", label: "类型", width: 90 },
    {
      prop: "status",
      label: "状态",
      width: 90,
      status: {
        pending: { type: "warning", text: "待支付" },
        paid: { type: "success", text: "已支付" },
        closed: { type: "info", text: "已关闭" },
      },
    },
    { prop: "created_time", label: "创建时间", width: 168, sortable: true },
  ]
);

async function load() {
  if (!currentApp.value) {
    subscriptions.value = [];
    orders.value = [];
    return;
  }
  loading.value = true;
  try {
    const [subscriptionResponse, orderResponse] = await Promise.all([
      BillingAPI.subscriptions(typeFilter.value || undefined),
      BillingAPI.orders(typeFilter.value || undefined),
    ]);
    subscriptions.value = subscriptionResponse.data.data || [];
    orders.value = orderResponse.data.data || [];
  } finally {
    loading.value = false;
  }
}
function handleSearch(value: Record<string, unknown>) {
  submittedQuery.value = {
    keyword: String(value.keyword || ""),
    status: String(value.status || ""),
  };
  pageNo.value = 1;
}
function handleReset() {
  Object.assign(query, { keyword: "", status: "" });
  submittedQuery.value = { keyword: "", status: "" };
  pageNo.value = 1;
}
function handleSizeChange(size: number) {
  pageSize.value = size;
  pageNo.value = 1;
}
function handleCurrentChange(page: number) {
  pageNo.value = page;
}
function resetPage() {
  handleReset();
}
async function changeSubscriptionStatus(row: SubscriptionInfo, status: string) {
  if (row.status === status) return;
  const { value: reason } = await ElMessageBox.prompt(
    `将 ${row.display_name || row.username} 的订阅状态修正为“${subscriptionStatusName(status)}”，不会修改或删除已有积分。请输入原因：`,
    "修正订阅状态",
    { inputPattern: /\S{2,}/, inputErrorMessage: "至少输入2个字符", type: "warning" }
  );
  await BillingAPI.setSubscriptionStatus(row.id!, status, reason);
  ElMessage.success("订阅状态已修正");
  await load();
}

watch(() => currentApp.value?.id, load, { immediate: true });
</script>

<style scoped>
.ops-page {
  min-height: 0;
}
</style>
