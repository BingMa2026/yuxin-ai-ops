<script setup lang="ts">
import FinanceSearchBar from "@/views/module_finance/components/FinanceSearchBar.vue";
import { computed, ref, watch, onUnmounted } from "vue";
import { useRoute } from "vue-router";
import { resolveStatusColumns, renderTableOperationCell, makeStatusFormatter } from "@utils";
import API, { type Bill, type BillEntry, type Provider } from "@/api/module_finance";
import FaTableHeader from "@/components/tables/fa-table-header/index.vue";
import OrderDrawer from "../components/OrderDrawer.vue";
import {
  dateTime,
  money,
  providerName,
  reasonPrompt,
  searchFields,
  states,
  matchStates,
  useFinanceList,
} from "../shared";
const route = useRoute();
const {
  currentApp,
  rows,
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
} = useFinanceList(API.bills);
const searchItems = searchFields(
  ["queued", "downloading", "completed", "failed"],
  "账单日期通过日期范围筛选",
  false
).filter((f) => f.key !== "keyword");
const createOpen = ref(false),
  provider = ref<Provider>("alipay"),
  days = ref<[string, string] | null>(null);
const automation = ref<{ enabled: boolean; hour: number } | null>(null);
const shanghaiDate = (date: Date) =>
  new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(date);
const shortcuts = [1, 7, 30].map((count) => ({
  text: count === 1 ? "昨天" : `最近${count}个完整账期`,
  value: () => [new Date(Date.now() - count * 86400000), new Date(Date.now() - 86400000)],
}));
const dayCount = computed(() =>
  days.value?.length === 2
    ? Math.round((Date.parse(days.value[1]) - Date.parse(days.value[0])) / 86400000) + 1
    : 0
);
function openCreate() {
  const yesterday = shanghaiDate(new Date(Date.now() - 86400000));
  days.value = [yesterday, yesterday];
  createOpen.value = true;
}
async function requestRange() {
  if (busy.value || !days.value || dayCount.value < 1 || dayCount.value > 31) return;
  const scope = currentApp.value?.id;
  busy.value = true;
  try {
    await API.requestBillBatch(provider.value, days.value[0], days.value[1]);
    if (scope === currentApp.value?.id) {
      createOpen.value = false;
      await load();
    }
  } finally {
    busy.value = false;
  }
}
watch(
  () => currentApp.value?.id,
  async (scope) => {
    automation.value = null;
    if (!scope) return;
    try {
      const result = (await API.billAutomation()).data.data;
      if (scope === currentApp.value?.id) automation.value = result;
    } catch {
      /* The request layer displays the error; never claim automation is active. */
    }
  },
  { immediate: true }
);
const progressTimer = setInterval(() => {
  if (
    !document.hidden &&
    !loading.value &&
    !busy.value &&
    rows.value.some((row) => ["queued", "downloading"].includes(row.status))
  )
    void load();
}, 5000);
onUnmounted(() => clearInterval(progressTimer));
const drawer = ref(false),
  selected = ref<Bill | null>(null),
  entries = ref<BillEntry[]>([]),
  entryPage = ref(1),
  entryTotal = ref(0),
  entryLoading = ref(false),
  entryFailed = ref(false),
  entryStatus = ref(""),
  entryKeyword = ref(String(route.query.keyword || ""));
const orderOpen = ref(false),
  orderId = ref<number | null>(null);
const entryPagination = computed(() => ({
  current: entryPage.value,
  size: 20,
  total: entryTotal.value,
}));
let generation = 0;
async function entriesLoad() {
  const stamp = ++generation;
  if (!selected.value) return;
  entryLoading.value = true;
  entryFailed.value = false;
  try {
    const data = (
      await API.billEntries(selected.value.id, {
        page_no: entryPage.value,
        page_size: 20,
        status: entryStatus.value || undefined,
        keyword: entryKeyword.value || undefined,
      })
    ).data.data;
    if (stamp === generation) {
      entries.value = data.items;
      entryTotal.value = data.total;
    }
  } catch {
    if (stamp === generation) {
      entryFailed.value = true;
      entries.value = [];
    }
  } finally {
    if (stamp === generation) entryLoading.value = false;
  }
}
function details(row: Bill) {
  selected.value = row;
  drawer.value = true;
  entryPage.value = 1;
  entries.value = [];
  entryStatus.value = "";
  void entriesLoad();
}
async function requestBill(p: Provider, d: string) {
  if (busy.value || !d) return;
  const scope = currentApp.value?.id;
  busy.value = true;
  try {
    await API.requestBill(p, d);
    if (scope === currentApp.value?.id) {
      createOpen.value = false;
      await load();
    }
  } finally {
    busy.value = false;
  }
}
async function resolve(row: BillEntry) {
  if (busy.value) return;
  const scope = currentApp.value?.id;
  const reason = await reasonPrompt(
    `${row.order_no}：渠道 ${money(row.channel_amount_fen)}，系统 ${money(row.system_amount_fen)}。请记录核对依据和关联凭证编号；原差异数据会保留。`,
    "登记差异处理结论"
  );
  if (!reason || scope !== currentApp.value?.id) return;
  busy.value = true;
  try {
    await API.resolveEntry(row.id, reason);
    if (scope === currentApp.value?.id) await entriesLoad();
  } finally {
    busy.value = false;
  }
}
const { columnChecks, columns } = useTableColumns<Bill>(
  resolveStatusColumns<Bill>(() => [
    { prop: "bill_date", label: "账单日期", width: 130 },
    { prop: "provider", label: "渠道", width: 110, formatter: (r) => providerName(r.provider) },
    { prop: "status", label: "任务状态", width: 135, status: states },
    {
      prop: "entries",
      label: "当前客户端流水",
      width: 145,
      formatter: (r) => r.summary.entries ?? "—",
    },
    { prop: "matched", label: "匹配笔数", width: 105, formatter: (r) => r.summary.matched ?? "—" },
    {
      prop: "differences",
      label: "原始差异",
      width: 105,
      formatter: (r) => r.summary.differences ?? "—",
    },
    {
      prop: "payment_fen",
      label: "账单收款",
      minWidth: 135,
      align: "right",
      formatter: (r) => money(r.summary.payment_fen),
    },
    {
      prop: "refund_fen",
      label: "账单退款",
      minWidth: 135,
      align: "right",
      formatter: (r) => money(r.summary.refund_fen),
    },
    {
      prop: "fee_fen",
      label: "净手续费",
      minWidth: 125,
      align: "right",
      formatter: (r) => money(r.summary.fee_rows ? r.summary.fee_fen : null),
    },
    {
      prop: "requested_by",
      label: "任务来源",
      width: 130,
      formatter: (r) => (r.requested_by === 0 ? "系统自动" : `操作员 #${r.requested_by}`),
    },
    {
      prop: "created_time",
      label: "申请时间",
      minWidth: 175,
      formatter: (r) => dateTime(r.created_time),
    },
    {
      prop: "completed_at",
      label: "核对时间",
      minWidth: 175,
      formatter: (r) => dateTime(r.completed_at),
    },
    { prop: "error_message", label: "处理信息", minWidth: 240, showOverflowTooltip: true },
    {
      prop: "operation",
      label: "操作",
      width: 110,
      fixed: "right",
      formatter: (r) =>
        renderTableOperationCell([
          {
            key: "detail",
            label: "明细",
            artType: "custom",
            icon: "ri:file-list-line",
            run: () => details(r),
          },
          ...(r.status === "failed"
            ? [
                {
                  key: "retry",
                  label: "重试",
                  artType: "custom" as const,
                  icon: "ri:refresh-line",
                  perm: "workspace:finance:bill:manage",
                  run: () => void requestBill(r.provider, r.bill_date),
                },
              ]
            : []),
        ]),
    },
  ])
);
const entryColumns = computed(() => [
  { prop: "order_no", label: "商户订单号", minWidth: 225, showOverflowTooltip: true },
  { prop: "provider_trade_no", label: "渠道交易号", minWidth: 220, showOverflowTooltip: true },
  {
    prop: "entry_type",
    label: "流水类型",
    width: 100,
    formatter: (r: BillEntry) => (r.entry_type === "payment" ? "收款" : "退款"),
  },
  { prop: "refund_no", label: "退款单号", minWidth: 210, showOverflowTooltip: true },
  {
    prop: "channel_amount_fen",
    label: "渠道金额",
    width: 130,
    formatter: (r: BillEntry) => money(r.channel_amount_fen),
  },
  {
    prop: "system_amount_fen",
    label: "系统金额",
    width: 130,
    formatter: (r: BillEntry) => money(r.system_amount_fen),
  },
  { prop: "fee_fen", label: "手续费", width: 120, formatter: (r: BillEntry) => money(r.fee_fen) },
  {
    prop: "match_status",
    label: "核对结果",
    minWidth: 155,
    formatter: makeStatusFormatter<BillEntry>({
      valueGetter: (r) => r.match_status,
      map: matchStates,
    }),
  },
  { prop: "resolution", label: "处理结论", minWidth: 230, showOverflowTooltip: true },
  { prop: "resolved_by", label: "处理人ID", width: 105 },
  {
    prop: "resolved_at",
    label: "处理时间",
    minWidth: 175,
    formatter: (r: BillEntry) => dateTime(r.resolved_at),
  },
  {
    prop: "operation",
    label: "操作",
    width: 130,
    fixed: "right" as const,
    formatter: (r: BillEntry) =>
      renderTableOperationCell([
        ...(r.order_id
          ? [
              {
                key: "order",
                label: "订单",
                artType: "custom" as const,
                icon: "ri:bill-line",
                perm: "workspace:finance:order:list",
                run: () => {
                  orderId.value = r.order_id;
                  orderOpen.value = true;
                },
              },
            ]
          : []),
        ...(r.match_status !== "matched" && !r.resolved_at
          ? [
              {
                key: "resolve",
                label: "处理",
                artType: "custom" as const,
                icon: "ri:check-line",
                perm: "workspace:finance:bill:manage",
                run: () => void resolve(r),
              },
            ]
          : []),
      ]),
  },
]);
watch(
  () => currentApp.value?.id,
  () => {
    generation++;
    drawer.value = false;
    createOpen.value = false;
    orderOpen.value = false;
    selected.value = null;
    entries.value = [];
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
              v-hasPerm="['workspace:finance:bill:manage']"
              type="primary"
              @click="openCreate"
              ><FaSvgIcon icon="ri:download-cloud-line" />批量对账</ElButton
            ><span v-if="automation" class="automation-status">
              {{
                automation.enabled
                  ? `每天北京时间 ${String(automation.hour).padStart(2, "0")}:00 后自动核对昨日账单`
                  : "自动对账未开启"
              }}
            </span></template
          ></FaTableHeader
        ><ElAlert
          v-if="failed"
          title="账单列表加载失败，请重试"
          type="error"
          :closable="false" /><FaTable
          :loading="loading"
          :data="rows"
          :columns="columns"
          :pagination="pagination"
          @pagination:current-change="changePage"
          @pagination:size-change="changeSize" /></ElCard></template
    ><ElCard v-else class="fa-table-card"><ElEmpty description="请先选择客户端" /></ElCard>
    <ElDialog v-model="createOpen" title="批量获取并核对账单" width="min(580px,94vw)"
      ><ElForm label-position="top"
        ><ElFormItem label="渠道" required
          ><ElSelect v-model="provider"
            ><ElOption label="支付宝" value="alipay" /><ElOption
              label="微信支付"
              value="wechat" /></ElSelect></ElFormItem
        ><ElFormItem label="账单日期范围（北京时间，最多31天）" required
          ><ElDatePicker
            v-model="days"
            type="daterange"
            :shortcuts="shortcuts"
            range-separator="至"
            start-placeholder="开始日期"
            end-placeholder="结束日期"
            style="width: 100%"
            value-format="YYYY-MM-DD"
            :disabled-date="
              (date: Date) =>
                `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}` >=
                shanghaiDate(new Date())
            " /></ElFormItem></ElForm
      ><ElAlert
        title="按天分别核对，已完成的日期自动跳过，失败的日期重新排队。仅保存当前客户端匹配的流水；渠道尚未出账或没有账单时会显示原因。"
        type="info"
        :closable="false"
      /><template #footer
        ><ElButton @click="createOpen = false">取消</ElButton
        ><ElButton
          type="primary"
          :loading="busy"
          :disabled="dayCount < 1 || dayCount > 31"
          @click="requestRange"
          >提交 {{ dayCount || 0 }} 天对账</ElButton
        ></template
      ></ElDialog
    >
    <ElDrawer v-model="drawer" title="对账明细" size="min(1250px,96vw)"
      ><template v-if="selected"
        ><ElDescriptions :column="2" border
          ><ElDescriptionsItem label="账期">{{ selected.bill_date }}</ElDescriptionsItem
          ><ElDescriptionsItem label="渠道">{{
            providerName(selected.provider)
          }}</ElDescriptionsItem
          ><ElDescriptionsItem label="文件校验摘要" :span="2"
            ><span class="digest">{{
              selected.file_digest || "尚未下载"
            }}</span></ElDescriptionsItem
          ><ElDescriptionsItem label="下载时间">{{
            dateTime(selected.downloaded_at)
          }}</ElDescriptionsItem
          ><ElDescriptionsItem label="核对时间">{{
            dateTime(selected.completed_at)
          }}</ElDescriptionsItem></ElDescriptions
        ><ElAlert
          v-if="selected.summary.excluded_merchant_rows"
          class="entry-filter"
          :title="`该商户账单另有 ${selected.summary.excluded_merchant_rows} 条非当前客户端流水，未纳入本客户端明细。`"
          type="info"
          :closable="false" /><ElAlert
          v-if="selected.error_message"
          :title="selected.error_message"
          type="error"
          :closable="false" />
        <div class="entry-filter">
          <ElInput
            v-model="entryKeyword"
            placeholder="订单号或退款号"
            clearable
            @keyup.enter="
              entryPage = 1;
              entriesLoad();
            "
          /><ElSelect v-model="entryStatus" placeholder="全部核对结果" clearable
            ><ElOption
              v-for="(value, key) in matchStates"
              :key="key"
              :label="value.text"
              :value="key" /></ElSelect
          ><ElButton
            type="primary"
            @click="
              entryPage = 1;
              entriesLoad();
            "
            >查询</ElButton
          >
        </div>
        <ElAlert
          v-if="entryFailed"
          title="明细加载失败，请重试"
          type="error"
          :closable="false" /><FaTable
          :loading="entryLoading"
          :data="entries"
          :columns="entryColumns"
          :pagination="entryPagination"
          @pagination:current-change="
            entryPage = $event;
            entriesLoad();
          " /></template></ElDrawer
    ><OrderDrawer v-model="orderOpen" :order-id="orderId" />
  </main>
</template>
<style scoped>
.automation-status {
  margin-left: 12px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.entry-filter {
  display: flex;
  gap: 12px;
  margin: 18px 0;
  flex-wrap: wrap;
}
.entry-filter .el-input,
.entry-filter .el-select {
  width: 220px;
}
.digest {
  overflow-wrap: anywhere;
  font-family: monospace;
}
</style>
