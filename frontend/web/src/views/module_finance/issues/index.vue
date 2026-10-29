<script setup lang="ts">
import FinanceSearchBar from "@/views/module_finance/components/FinanceSearchBar.vue";
import { useRouter } from "vue-router";
import { resolveStatusColumns, renderTableOperationCell } from "@utils";
import API, { type Issue } from "@/api/module_finance";
import FaTableHeader from "@/components/tables/fa-table-header/index.vue";
import {
  dateTime,
  money,
  providerName,
  reasonPrompt,
  searchFields,
  states,
  useFinanceList,
} from "../shared";
const router = useRouter();
const {
  currentApp,
  rows,
  total,
  loading,
  failed,
  busy,
  query,
  pagination,
  showSearchBar,
  load,
  search,
  reset,
  changePage,
  changeSize,
} = useFinanceList(API.issues);
const searchItems = searchFields(
  ["unresolved", "open", "processing", "resolved"],
  "业务单号 / 异常内容",
  false
);
const kinds: Record<string, string> = {
  payment_failed: "支付失败",
  fulfillment_missing: "权益未到账",
  refund_unknown: "退款结果未明",
  payout_unknown: "转账结果未明",
  reconciliation_difference: "对账差异",
};
async function act(row: Issue, action: "claim" | "resolve" | "reopen") {
  if (busy.value) return;
  const scope = currentApp.value?.id;
  const reason = await reasonPrompt(
    `${row.order_no || `#${row.id}`}：${row.detail}`,
    action === "claim" ? "认领异常" : action === "resolve" ? "核验并关闭异常" : "重新打开异常"
  );
  if (!reason || scope !== currentApp.value?.id) return;
  busy.value = true;
  try {
    await API.issueAction(row.id, action, reason);
    if (scope === currentApp.value?.id) await load();
  } finally {
    busy.value = false;
  }
}
async function refresh() {
  if (busy.value) return;
  const scope = currentApp.value?.id;
  busy.value = true;
  try {
    await API.refreshIssues();
    if (scope === currentApp.value?.id) await load();
  } finally {
    busy.value = false;
  }
}
function source(row: Issue) {
  const path =
    row.object_type === "refund"
      ? "/finance/refunds"
      : row.object_type === "payout"
        ? "/finance/growth-payout"
        : row.object_type === "bill_entry"
          ? "/finance/bills"
          : "/finance/orders";
  void router.push({ path, query: { keyword: row.order_no || "" } });
}
const { columnChecks, columns } = useTableColumns<Issue>(
  resolveStatusColumns<Issue>(() => [
    {
      prop: "severity",
      label: "优先级",
      width: 100,
      status: {
        high: { type: "danger", text: "高" },
        medium: { type: "warning", text: "中" },
        low: { type: "info", text: "低" },
      },
    },
    { prop: "kind", label: "异常类型", minWidth: 150, formatter: (r) => kinds[r.kind] || r.kind },
    { prop: "order_no", label: "关联业务单号", minWidth: 225, showOverflowTooltip: true },
    { prop: "provider", label: "渠道", width: 105, formatter: (r) => providerName(r.provider) },
    {
      prop: "amount_fen",
      label: "涉及金额",
      width: 135,
      align: "right",
      formatter: (r) => money(r.amount_fen),
    },
    { prop: "status", label: "处理状态", width: 115, status: states },
    { prop: "detail", label: "异常内容", minWidth: 250, showOverflowTooltip: true },
    { prop: "assigned_to", label: "处理人ID", width: 110 },
    {
      prop: "created_time",
      label: "首次发现",
      minWidth: 175,
      formatter: (r) => dateTime(r.created_time),
    },
    {
      prop: "last_seen_at",
      label: "最近核验",
      minWidth: 175,
      formatter: (r) => dateTime(r.last_seen_at),
    },
    { prop: "resolution", label: "处理结论", minWidth: 220, showOverflowTooltip: true },
    {
      prop: "resolved_at",
      label: "处理时间",
      minWidth: 175,
      formatter: (r) => dateTime(r.resolved_at),
    },
    {
      prop: "operation",
      label: "操作",
      width: 185,
      fixed: "right",
      formatter: (r) =>
        renderTableOperationCell([
          {
            key: "source",
            label: "关联业务",
            artType: "custom",
            icon: "ri:external-link-line",
            run: () => source(r),
          },
          ...(r.status === "open"
            ? [
                {
                  key: "claim",
                  label: "认领",
                  artType: "custom" as const,
                  icon: "ri:user-follow-line",
                  perm: "workspace:finance:issue:manage",
                  run: () => void act(r, "claim"),
                },
              ]
            : []),
          {
            key: "resolve",
            label: r.status === "resolved" ? "重开" : "核验关闭",
            artType: "custom",
            icon: "ri:checkbox-circle-line",
            perm: "workspace:finance:issue:manage",
            run: () => void act(r, r.status === "resolved" ? "reopen" : "resolve"),
          },
        ]),
    },
  ])
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
        @update:model-value="Object.assign(query, $event)"
        @search="search"
        @reset="reset" /><ElCard
        class="fa-table-card"
        :style="{ marginTop: showSearchBar ? '12px' : '0' }"
        ><FaTableHeader
          v-model:columns="columnChecks"
          v-model:showSearchBar="showSearchBar"
          :loading="loading"
          @refresh="load"
          ><template #left
            ><ElButton
              v-hasPerm="['workspace:finance:issue:manage']"
              type="primary"
              :loading="busy"
              @click="refresh"
              ><FaSvgIcon icon="ri:shield-check-line" />重新核验</ElButton
            ><span class="summary">{{ total }} 条异常记录</span></template
          ></FaTableHeader
        ><ElAlert
          v-if="failed"
          title="异常待办加载失败，请重试"
          type="error"
          :closable="false" /><FaTable
          :loading="loading"
          :data="rows"
          :columns="columns"
          :pagination="pagination"
          @pagination:current-change="changePage"
          @pagination:size-change="changeSize" /></ElCard></template
    ><ElCard v-else class="fa-table-card"><ElEmpty description="请先选择客户端" /></ElCard>
  </main>
</template>
<style scoped>
.summary {
  margin-left: 12px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
</style>
