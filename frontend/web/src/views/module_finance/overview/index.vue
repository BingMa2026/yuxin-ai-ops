<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRouter } from "vue-router";
import { useClientAppStore } from "@stores";
import API, { type Metrics, type Overview } from "@/api/module_finance";
import FinanceChart from "../components/FinanceChart.vue";
import { dateTime, money, providerName } from "../shared";
const router = useRouter(),
  { currentApp } = storeToRefs(useClientAppStore());
const data = ref<Overview | null>(null),
  loading = ref(false),
  failed = ref(false),
  period = ref(30),
  dates = ref<string[]>([]);
function day(date: Date) {
  return new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Shanghai" }).format(date);
}
function preset(value: number) {
  period.value = value;
  const end = new Date();
  dates.value = [day(new Date(end.getTime() - (value - 1) * 86400000)), day(end)];
  void load();
}
let generation = 0;
async function load() {
  const stamp = ++generation;
  if (!currentApp.value || dates.value?.length !== 2) return;
  loading.value = true;
  failed.value = false;
  try {
    const result = (await API.overview({ start_date: dates.value[0]!, end_date: dates.value[1]! }))
      .data.data;
    if (stamp === generation) data.value = result;
  } catch {
    if (stamp === generation) {
      data.value = null;
      failed.value = true;
    }
  } finally {
    if (stamp === generation) loading.value = false;
  }
}
watch(
  () => currentApp.value?.id,
  () => {
    data.value = null;
    preset(period.value);
  },
  { immediate: true }
);
onBeforeUnmount(() => generation++);
const cards: { key: keyof Metrics; label: string; icon: string; money: boolean; hint: string }[] = [
  {
    key: "received_fen",
    label: "支付收款",
    icon: "ri:secure-payment-line",
    money: true,
    hint: "按渠道确认支付时间",
  },
  {
    key: "refund_fen",
    label: "成功退款",
    icon: "ri:refund-2-line",
    money: true,
    hint: "按渠道退款完成时间",
  },
  {
    key: "net_received_fen",
    label: "收款净额",
    icon: "ri:funds-line",
    money: true,
    hint: "支付收款 − 成功退款",
  },
  {
    key: "payout_fen",
    label: "推广支出",
    icon: "ri:wallet-3-line",
    money: true,
    hint: "已成功到账的佣金提现",
  },
  {
    key: "paid_orders",
    label: "成交订单",
    icon: "ri:bill-line",
    money: false,
    hint: "渠道已确认支付的订单",
  },
  {
    key: "average_order_fen",
    label: "成交客单价",
    icon: "ri:bar-chart-grouped-line",
    money: true,
    hint: "支付收款 ÷ 成交订单",
  },
];
function delta(key: keyof Metrics) {
  if (!data.value) return "—";
  const a = data.value.current[key],
    b = data.value.previous[key];
  if (!b) return a ? "上期为零" : "与上期持平";
  const pct = ((a - b) / Math.abs(b)) * 100;
  return `${pct > 0 ? "+" : ""}${pct.toFixed(1)}% 较上期`;
}
function openOrders() {
  if (!data.value) return;
  void router.push({
    path: "/finance/orders",
    query: {
      start_date: data.value.start_date,
      end_date: data.value.end_date,
      time_field: "paid_at",
      status: "paid",
    },
  });
}
const tasks = computed(() => [
  {
    key: "refund_review",
    name: "退款待审核",
    icon: "ri:refund-2-line",
    path: "/finance/refunds",
    status: "review",
    permission: "workspace:finance:refund:list",
  },
  {
    key: "payout_review",
    name: "提现待审核",
    icon: "ri:wallet-3-line",
    path: "/finance/growth-payout",
    status: "review",
    permission: "workspace:finance:payout:list",
  },
  {
    key: "payout_processing",
    name: "转账处理中",
    icon: "ri:time-line",
    path: "/finance/growth-payout",
    status: "inflight",
    permission: "workspace:finance:payout:list",
  },
  {
    key: "open_issues",
    name: "未结异常",
    icon: "ri:alarm-warning-line",
    path: "/finance/issues",
    status: "unresolved",
    permission: "workspace:finance:issue:list",
  },
]);
</script>
<template>
  <main class="finance-overview">
    <ElEmpty v-if="!currentApp" description="请先选择客户端" /><template v-else>
      <div class="overview-filters">
        <ElRadioGroup :model-value="period" size="default" @change="preset(Number($event))"
          ><ElRadioButton :value="1">今日</ElRadioButton
          ><ElRadioButton :value="7">近7天</ElRadioButton
          ><ElRadioButton :value="30">近30天</ElRadioButton
          ><ElRadioButton :value="90">近90天</ElRadioButton></ElRadioGroup
        ><ElDatePicker
          v-model="dates"
          type="daterange"
          value-format="YYYY-MM-DD"
          start-placeholder="开始日期"
          end-placeholder="结束日期"
          :clearable="false"
          @change="
            period = 0;
            load();
          "
        /><ElButton :loading="loading" @click="load"
          ><FaSvgIcon icon="ri:refresh-line" />刷新</ElButton
        ><span v-if="data" class="updated">更新于 {{ dateTime(data.generated_at) }}</span>
      </div>
      <ElSkeleton v-if="loading && !data" :rows="16" animated /><ElResult
        v-else-if="failed"
        icon="error"
        title="财务数据加载失败"
        ><template #extra
          ><ElButton type="primary" @click="load">重试</ElButton></template
        ></ElResult
      >
      <template v-else-if="data"
        ><section class="metric-grid" v-loading="loading">
          <article
            v-for="card in cards"
            :key="card.key"
            class="metric"
            :class="{ 'metric-primary': card.key === 'net_received_fen' }"
          >
            <div class="metric-label">{{ card.label }}<FaSvgIcon :icon="card.icon" /></div>
            <strong>{{
              card.money ? money(data.current[card.key]) : data.current[card.key].toLocaleString()
            }}</strong>
            <div class="metric-change">{{ delta(card.key) }}</div>
            <small>{{ card.hint }}</small>
          </article>
        </section>
        <section class="task-grid">
          <button
            v-for="task in tasks"
            :key="task.key"
            v-hasPerm="[task.permission]"
            class="task"
            @click="router.push({ path: task.path, query: { status: task.status } })"
          >
            <FaSvgIcon :icon="task.icon" /><span>{{ task.name }}</span
            ><strong :class="{ 'task-alert': data.tasks[task.key] }">{{
              data.tasks[task.key] || 0
            }}</strong
            ><FaSvgIcon icon="ri:arrow-right-s-line" />
          </button>
        </section>
        <section class="chart-grid">
          <ElCard shadow="never" class="trend-card"
            ><div class="chart-label">
              <span>资金变动趋势</span
              ><ElButton
                v-hasPerm="['workspace:finance:order:list']"
                link
                type="primary"
                @click="openOrders"
                >查看交易明细 <FaSvgIcon icon="ri:arrow-right-up-line"
              /></ElButton>
            </div>
            <FinanceChart :data="data" kind="trend" /></ElCard
          ><ElCard shadow="never"
            ><div class="chart-label">收款渠道构成</div>
            <FinanceChart v-if="data.current.received_fen" :data="data" kind="channel" /><ElEmpty
              v-else
              description="所选周期暂无成功收款"
              :image-size="100"
              class="chart-empty"
          /></ElCard>
        </section>
        <section class="bottom-grid">
          <ElCard shadow="never"
            ><div class="chart-label">渠道交易表现</div>
            <ElTable :data="data.channels"
              ><ElTableColumn label="渠道" min-width="105"
                ><template #default="{ row }">{{
                  providerName(row.provider)
                }}</template></ElTableColumn
              ><ElTableColumn label="支付收款" min-width="140" align="right"
                ><template #default="{ row }">{{
                  money(row.received_fen)
                }}</template></ElTableColumn
              ><ElTableColumn
                prop="paid_orders"
                label="成交订单"
                width="100"
                align="right"
              /><ElTableColumn label="成功退款" min-width="130" align="right"
                ><template #default="{ row }">{{ money(row.refund_fen) }}</template></ElTableColumn
              ><ElTableColumn label="下单支付转化" min-width="135" align="right"
                ><template #default="{ row }"
                  ><ElTooltip
                    :content="`所选周期内创建 ${row.created_orders} 笔，截至当前已支付 ${row.converted_orders} 笔`"
                    ><span>{{
                      row.conversion_rate === null ? "—" : `${row.conversion_rate.toFixed(1)}%`
                    }}</span></ElTooltip
                  ></template
                ></ElTableColumn
              ></ElTable
            ></ElCard
          >
          <ElCard shadow="never"
            ><div class="chart-label">推广资金待办</div>
            <dl class="balance-list">
              <div>
                <dt>用户可提现余额</dt>
                <dd>{{ money(data.promotion_balances.available_fen) }}</dd>
              </div>
              <div>
                <dt>提现冻结金额</dt>
                <dd>{{ money(data.promotion_balances.frozen_fen) }}</dd>
              </div>
              <div>
                <dt>奖励冲正待抵扣</dt>
                <dd>{{ money(data.promotion_balances.debt_fen) }}</dd>
              </div>
            </dl></ElCard
          >
        </section>
        <ElCard shadow="never" class="reconciliation-card"
          ><div class="chart-label">
            <span>账单核对进度</span
            ><ElButton
              v-hasPerm="['workspace:finance:bill:list']"
              link
              type="primary"
              @click="router.push('/finance/bills')"
              >进入对账 <FaSvgIcon icon="ri:arrow-right-up-line"
            /></ElButton>
          </div>
          <div class="reconciliation-grid">
            <div>
              <span>已核对账单</span><strong>{{ data.reconciliation.completed_days }} 份</strong>
            </div>
            <div>
              <span>下载失败</span><strong>{{ data.reconciliation.failed_days }} 份</strong>
            </div>
            <div>
              <span>原始差异流水</span
              ><strong>{{ data.reconciliation.difference_count }} 笔</strong>
            </div>
            <div>
              <span>已核验收款手续费</span
              ><strong>{{ money(data.reconciliation.verified_fee_fen) }}</strong>
            </div>
          </div></ElCard
        >
      </template></template
    >
  </main>
</template>
<style scoped>
.finance-overview {
  display: grid;
  gap: 18px;
  padding-bottom: 20px;
}
.overview-filters {
  display: flex;
  gap: 12px;
  align-items: center;
  flex-wrap: wrap;
}
.overview-filters :deep(.el-date-editor) {
  max-width: 290px;
}
.updated {
  margin-left: auto;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.metric-grid {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 14px;
}
.metric {
  padding: 20px 18px;
  border: 1px solid var(--el-border-color-lighter);
  background: var(--el-bg-color);
  border-radius: 12px;
  min-width: 0;
}
.metric-primary {
  border-color: var(--el-color-primary-light-5);
  background: linear-gradient(145deg, var(--el-color-primary-light-9), var(--el-bg-color));
}
.metric-label {
  display: flex;
  align-items: center;
  justify-content: space-between;
  color: var(--el-text-color-regular);
  font-size: 13px;
}
.metric-label :deep(svg) {
  color: var(--el-color-primary);
  font-size: 18px;
}
.metric > strong {
  display: block;
  margin: 18px 0 8px;
  font-size: clamp(20px, 1.7vw, 30px);
  letter-spacing: -0.6px;
  font-variant-numeric: tabular-nums;
  overflow-wrap: anywhere;
}
.metric-change {
  font-size: 12px;
  margin-bottom: 10px;
  color: var(--el-text-color-regular);
}
.metric small {
  font-size: 11px;
  color: var(--el-text-color-secondary);
}
.task-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}
.task {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px;
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 10px;
  color: var(--el-text-color-regular);
  cursor: pointer;
  text-align: left;
}
.task:hover {
  border-color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
}
.task strong {
  margin-left: auto;
  font-size: 24px;
  font-variant-numeric: tabular-nums;
}
.task .task-alert {
  color: var(--el-color-danger);
}
.chart-grid {
  display: grid;
  grid-template-columns: 2fr 1fr;
  gap: 18px;
}
.chart-label {
  font-size: 15px;
  font-weight: 600;
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 30px;
  margin-bottom: 12px;
}
.chart-empty {
  height: 320px;
}
.bottom-grid {
  display: grid;
  grid-template-columns: 2fr 1fr;
  gap: 18px;
}
.balance-list {
  margin: 0;
}
.balance-list > div {
  display: flex;
  justify-content: space-between;
  padding: 15px 0;
  border-bottom: 1px solid var(--el-border-color-lighter);
  gap: 16px;
}
.balance-list > div:last-child {
  border: 0;
}
.balance-list dt {
  color: var(--el-text-color-secondary);
  font-size: 13px;
}
.balance-list dd {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}
.reconciliation-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 20px;
}
.reconciliation-grid span {
  display: block;
  color: var(--el-text-color-secondary);
  font-size: 12px;
  margin-bottom: 8px;
}
.reconciliation-grid strong {
  font-size: 22px;
  font-variant-numeric: tabular-nums;
}
.el-card {
  border-radius: 12px;
}
@media (max-width: 1400px) {
  .metric-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}
@media (max-width: 950px) {
  .chart-grid,
  .bottom-grid {
    grid-template-columns: 1fr;
  }
  .task-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .metric-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .reconciliation-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}
@media (max-width: 480px) {
  .task-grid {
    grid-template-columns: 1fr;
  }
  .metric {
    padding: 15px 12px;
  }
  .overview-filters :deep(.el-date-editor) {
    width: 100%;
    max-width: none;
  }
  .updated {
    margin-left: 0;
  }
  .reconciliation-grid strong {
    font-size: 18px;
  }
}
</style>
