<script setup lang="ts">
import FinanceSearchBar from "@/views/module_finance/components/FinanceSearchBar.vue";
import { ref, watch } from "vue";
import { useRoute } from "vue-router";
import FinanceAPI, { type Payout } from "@/api/module_finance";
import {
  dateTime,
  money,
  searchFields,
  states,
  useFinanceList,
} from "@/views/module_finance/shared";
import { ElMessageBox } from "element-plus";
import FaTableHeader from "@/components/tables/fa-table-header/index.vue";
import { resolveStatusColumns, renderTableOperationCell } from "@utils";
import API, { type Withdrawal, type PayoutAttempt } from "@/api/module_growth/payout";
const route = useRoute();
const {
  currentApp,
  rows,
  summary,
  total,
  page,
  loading,
  failed,
  busy,
  query: filters,
  pagination,
  showSearchBar,
  load: loadRows,
  search,
  reset,
  changePage,
  changeSize,
} = useFinanceList(FinanceAPI.payouts, {
  keyword: String(route.query.keyword || ""),
  status: String(route.query.status || ""),
});
const searchItems = searchFields(
  [
    "review",
    "inflight",
    "queued",
    "unknown",
    "processing",
    "confirming",
    "succeeded",
    "failed",
    "rejected",
  ],
  "提现单号 / 用户"
);
const capabilities = ref<{ provider: string; available: boolean; reason: string }[]>([]);
const details = ref<PayoutAttempt[]>([]),
  detailVisible = ref(false);
const labels: Record<string, string> = {
  review: "待审核",
  queued: "待转账",
  unknown: "结果未明",
  processing: "渠道处理中",
  confirming: "待用户确认收款",
  succeeded: "已到账",
  failed: "已失败 / 解冻",
  rejected: "已拒绝 / 解冻",
};
const { columnChecks, columns } = useTableColumns<Payout>(
  resolveStatusColumns<Payout>(() => [
    { prop: "out_bill_no", label: "提现单号", minWidth: 200, showOverflowTooltip: true },
    {
      prop: "display_name",
      label: "用户",
      minWidth: 150,
      formatter: (r) => `${r.display_name || r.username} (#${r.user_id})`,
      showOverflowTooltip: true,
    },
    {
      prop: "provider",
      label: "渠道",
      width: 90,
      formatter: (r) => (r.provider === "wechat" ? "微信" : "支付宝"),
    },
    { prop: "payee", label: "收款账户", minWidth: 150 },
    {
      prop: "amount_fen",
      label: "金额",
      width: 110,
      formatter: (r) => `¥${(r.amount_fen / 100).toFixed(2)}`,
    },
    { prop: "status", label: "状态", minWidth: 150, status: states },
    { prop: "provider_bill_no", label: "渠道转账单号", minWidth: 220, showOverflowTooltip: true },
    {
      prop: "created_time",
      label: "申请时间",
      minWidth: 175,
      formatter: (r) => dateTime(r.created_time),
    },
    {
      prop: "reviewed_at",
      label: "审核时间",
      minWidth: 175,
      formatter: (r) => dateTime(r.reviewed_at),
    },
    {
      prop: "completed_at",
      label: "到账时间",
      minWidth: 175,
      formatter: (r) => dateTime(r.completed_at),
    },
    { prop: "attempt_count", label: "渠道交互次数", width: 120 },
    {
      prop: "next_attempt_at",
      label: "下次核验",
      minWidth: 175,
      formatter: (r) => dateTime(r.next_attempt_at),
    },
    { prop: "reason", label: "处理说明", minWidth: 180, showOverflowTooltip: true },
    {
      prop: "operation",
      label: "操作",
      fixed: "right",
      width: 180,
      formatter: (r) =>
        renderTableOperationCell([
          ...(r.status === "review"
            ? [true, false].map((approved) => ({
                key: String(approved),
                label: approved ? "通过" : "拒绝",
                artType: "custom" as const,
                icon: approved ? "ri:check-line" : "ri:close-line",
                perm: "workspace:finance:payout:review",
                run: () => void review(r, approved),
              }))
            : []),
          ...(["unknown", "processing", "confirming"].includes(r.status)
            ? [
                {
                  key: "query",
                  label: "查单",
                  artType: "custom" as const,
                  icon: "ri:search-line",
                  perm: "workspace:finance:payout:review",
                  run: () => void query(r.id),
                },
              ]
            : []),
          {
            key: "history",
            label: "处理记录",
            artType: "custom",
            icon: "ri:history-line",
            run: () => void showAttempts(r.id),
          },
        ]),
    },
  ])
);
let generation = 0;
async function load() {
  const stamp = ++generation;
  await loadRows();
  if (!currentApp.value) return;
  try {
    const result = (await API.capabilities()).data.data;
    if (stamp === generation) capabilities.value = result;
  } catch {
    if (stamp === generation) capabilities.value = [];
  }
}
async function review(row: Withdrawal, approved: boolean) {
  if (busy.value) return;
  const scope = currentApp.value?.id;
  const input = await ElMessageBox.prompt(
    `${approved ? "通过后进入真实渠道转账队列" : "拒绝后解冻余额"}：用户${row.user_id}，¥${(row.amount_fen / 100).toFixed(2)}，${row.payee}。请填写审核依据。`,
    "提现审核",
    { inputValidator: (v) => Boolean(v?.trim().length >= 2) || "请填写审核依据" }
  ).catch(() => null);
  if (!input || scope !== currentApp.value?.id) return;
  busy.value = true;
  try {
    await API.review(row.id, approved, input.value);
    await load();
  } finally {
    busy.value = false;
  }
}
async function query(id: number) {
  busy.value = true;
  try {
    await API.query(id);
    await load();
  } finally {
    busy.value = false;
  }
}
async function showAttempts(id: number) {
  const stamp = ++generation;
  const data = (await API.attempts(id)).data.data;
  if (stamp !== generation) return;
  details.value = data;
  detailVisible.value = true;
}
watch(
  () => currentApp.value?.id,
  () => {
    page.value = 1;
    rows.value = [];
    detailVisible.value = false;
    void load();
  },
  { immediate: true }
);
</script>
<template>
  <main class="fa-full-height">
    <ElCard v-if="!currentApp" class="fa-table-card"
      ><ElEmpty description="请先选择客户端"
    /></ElCard>
    <template v-else>
      <div class="payout-capabilities">
        <ElAlert
          v-for="c in capabilities"
          :key="c.provider"
          :type="c.available ? 'success' : 'info'"
          :title="`${c.provider === 'wechat' ? '微信' : '支付宝'}提现：${c.available ? '商户转账已配置' : c.reason}`"
          :closable="false"
          show-icon
        />
      </div>
      <FinanceSearchBar
        v-show="showSearchBar"
        :model-value="filters"
        :items="searchItems"
        :is-expand="false"
        @update:model-value="Object.assign(filters, $event)"
        @search="search"
        @reset="reset"
      />
      <ElCard class="fa-table-card" :style="{ marginTop: showSearchBar ? '12px' : '0' }">
        <FaTableHeader
          v-model:columns="columnChecks"
          v-model:showSearchBar="showSearchBar"
          :loading="loading"
          @refresh="load"
          ><template #left
            ><span>{{ total }} 笔 · 提现金额 {{ money(summary.amount_fen || 0) }}</span></template
          ></FaTableHeader
        >
        <ElAlert v-if="failed" title="提现记录加载失败，请重试" type="error" :closable="false" />
        <FaTable
          :loading="loading"
          :data="rows"
          :columns="columns"
          :pagination="pagination"
          @pagination:current-change="changePage"
          @pagination:size-change="changeSize"
        />
      </ElCard>
    </template>
    <ElDrawer v-model="detailVisible" title="提现处理记录" size="min(680px, 94vw)"
      ><ElTimeline
        ><ElTimelineItem
          v-for="item in details"
          :key="item.id"
          :timestamp="new Date(item.created_time).toLocaleString()"
          ><strong
            >{{
              { review: "审核", submit: "转账请求", query: "查单" }[item.action] || item.action
            }}
            · {{ labels[item.status] || item.status }}</strong
          >
          <p>{{ item.detail }}</p></ElTimelineItem
        ></ElTimeline
      ></ElDrawer
    >
  </main>
</template>
<style scoped>
.payout-capabilities {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}
.payout-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}
.el-pagination {
  margin-top: 16px;
  justify-content: flex-end;
}
</style>
