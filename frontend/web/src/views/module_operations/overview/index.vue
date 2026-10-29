<template>
  <main class="overview-page fa-full-height">
    <ElSkeleton v-if="loading && !overview" :rows="9" animated />
    <template v-else-if="currentApp && overview">
      <header class="overview-header">
        <div class="overview-actions">
          <ElTag :type="costStatusType" effect="plain" round>
            成本口径 · {{ costStatusLabel }}
          </ElTag>
          <ElSelect v-model="periodPreset" class="period-select" @change="handlePeriodChange">
            <ElOption
              v-for="item in periodOptions"
              :key="item.value"
              :label="item.label"
              :value="item.value"
            />
          </ElSelect>
          <ElDatePicker
            v-if="periodPreset === 'custom'"
            v-model="customRange"
            type="daterange"
            value-format="YYYY-MM-DD"
            start-placeholder="开始日期"
            end-placeholder="结束日期"
            :clearable="false"
            :disabled-date="disableFutureDate"
            @change="load"
          />
          <ElButton :loading="loading" @click="load">
            <FaSvgIcon icon="ri:refresh-line" />
            刷新
          </ElButton>
        </div>
      </header>

      <section class="metric-grid" aria-label="核心经营指标">
        <OverviewMetricCard
          label="净回款"
          :value="money(overview.summary.revenue_yuan)"
          :delta="deltaText(overview.summary.revenue_yuan, overview.previous.revenue_yuan)"
          :hint="`实收 ${money(overview.summary.gross_revenue_yuan)} · 退款 ${money(overview.summary.refund_yuan)}`"
          icon="ri:bank-card-line"
          tone="blue"
          :delta-tone="deltaTone(overview.summary.revenue_yuan, overview.previous.revenue_yuan)"
        />
        <OverviewMetricCard
          label="模型直接贡献"
          :value="money(overview.summary.direct_margin_yuan)"
          :delta="`${overview.summary.direct_margin_rate.toFixed(1)}% 直接毛利率`"
          :hint="
            overview.summary.unknown_cost_calls
              ? '部分成本待确认，毛利暂不完整'
              : '含语音成本，未计渠道与人力'
          "
          icon="ri:line-chart-line"
          tone="green"
          :delta-tone="overview.summary.direct_margin_yuan >= 0 ? 'positive' : 'negative'"
        />
        <OverviewMetricCard
          label="模型使用成本"
          :value="money(overview.summary.provider_cost_yuan, 4)"
          :delta="
            deltaText(overview.summary.provider_cost_yuan, overview.previous.provider_cost_yuan)
          "
          :hint="`含语音 ${money(overview.summary.speech_cost_yuan, 4)} · ${costStatusLabel}`"
          icon="ri:cpu-line"
          tone="amber"
          :delta-tone="costDeltaTone"
        />
        <OverviewMetricCard
          label="周期活跃用户"
          :value="integer(overview.summary.active_users)"
          :delta="deltaText(overview.summary.active_users, overview.previous.active_users)"
          :hint="`${overview.summary.new_users} 位新用户`"
          icon="ri:user-smile-line"
          tone="violet"
          :delta-tone="deltaTone(overview.summary.active_users, overview.previous.active_users)"
        />
        <OverviewMetricCard
          label="模型调用成功率"
          :value="`${overview.summary.model_success_rate.toFixed(1)}%`"
          :delta="`${integer(overview.summary.model_calls)} 次调用`"
          :hint="`${compact(overview.summary.total_tokens)} Token`"
          icon="ri:pulse-line"
          tone="slate"
          :delta-tone="overview.summary.model_success_rate >= 95 ? 'positive' : 'negative'"
        />
      </section>

      <ElAlert
        v-if="overview.summary.unknown_cost_calls"
        type="warning"
        :closable="false"
        show-icon
        :title="`${overview.summary.unknown_cost_calls} 次调用成本待确认，以下成本与毛利仅按已知金额计算，不能视为最终账单。`"
      />

      <section class="equation-card" aria-label="经营因果关系">
        <div class="equation-card__title">
          <span>收入与成本</span>
          <small>直接贡献仅扣除模型采购成本，用于判断定价健康度</small>
        </div>
        <div class="equation-card__formula">
          <div>
            <span>实收回款</span><strong>{{ money(overview.summary.gross_revenue_yuan) }}</strong>
          </div>
          <b>−</b>
          <div>
            <span>退款</span><strong>{{ money(overview.summary.refund_yuan) }}</strong>
          </div>
          <b>=</b>
          <div>
            <span>净回款</span><strong>{{ money(overview.summary.net_revenue_yuan) }}</strong>
          </div>
          <b>−</b>
          <div>
            <span>模型使用成本</span
            ><strong>{{ money(overview.summary.provider_cost_yuan, 4) }}</strong>
          </div>
          <b>=</b>
          <div class="formula-result">
            <span>模型直接贡献</span
            ><strong>{{ money(overview.summary.direct_margin_yuan) }}</strong>
          </div>
        </div>
      </section>

      <section class="dashboard-grid dashboard-grid--main">
        <article class="panel panel--wide">
          <header class="panel__head">
            <div>
              <h2>营收与模型成本趋势</h2>
              <p>含对话及语音识别成本，按请求完成时间统计；供应商账单单独核对</p>
            </div>
            <span>{{ periodLabel }}</span>
          </header>
          <FaECharts :options="valueTrendOptions" height="300px" />
        </article>
        <article class="panel health-panel">
          <header class="panel__head">
            <div>
              <h2>运营健康度</h2>
              <p>当前需要持续关注的执行指标</p>
            </div>
          </header>
          <div class="health-list">
            <div v-for="item in healthItems" :key="item.label">
              <span>{{ item.label }}</span>
              <strong :class="item.tone">{{ item.value }}</strong>
              <ElProgress :percentage="item.percentage" :show-text="false" :status="item.status" />
            </div>
          </div>
        </article>
      </section>

      <section class="dashboard-grid">
        <article class="panel panel--wide">
          <header class="panel__head">
            <div>
              <h2>用户增长与活跃</h2>
              <p>注册、使用、付费分别来自用户、遥测/模型和订单数据</p>
            </div>
          </header>
          <FaECharts :options="userTrendOptions" height="276px" />
        </article>
        <article class="panel funnel-panel">
          <header class="panel__head">
            <div>
              <h2>用户经营漏斗</h2>
              <p>同一统计周期内的真实用户去重</p>
            </div>
          </header>
          <div class="funnel-list">
            <div v-for="(item, index) in overview.user_funnel" :key="item.code">
              <div>
                <span>{{ item.name }}</span
                ><strong>{{ integer(item.count) }}</strong>
              </div>
              <div class="funnel-track">
                <i :style="{ width: `${funnelWidth(item.count)}%` }" />
              </div>
              <small v-if="index > 0">上一步转化 {{ funnelConversion(index) }}</small>
            </div>
          </div>
        </article>
      </section>

      <section class="dashboard-grid dashboard-grid--thirds">
        <article class="panel">
          <header class="panel__head">
            <div>
              <h2>用户等级结构</h2>
              <p>等级规则的当前评估结果</p>
            </div>
          </header>
          <FaECharts :options="levelOptions" height="254px" />
        </article>
        <article class="panel">
          <header class="panel__head">
            <div>
              <h2>订阅结构</h2>
              <p>有效订阅与周期内实收</p>
            </div>
          </header>
          <div v-if="overview.subscription_distribution.length" class="plan-list">
            <div v-for="item in overview.subscription_distribution" :key="item.code">
              <span
                ><b>{{ item.name }}</b
                ><small>{{ integer(item.count) }} 位订阅用户</small></span
              >
              <strong>{{ money(item.revenue_yuan) }}</strong>
            </div>
          </div>
          <ElEmpty v-else :image-size="62" description="暂无有效订阅" />
        </article>
        <article class="panel">
          <header class="panel__head">
            <div>
              <h2>服务与权益</h2>
              <p>服务负载和待履约权益</p>
            </div>
          </header>
          <div class="service-grid">
            <div>
              <span>待处理工单</span><strong>{{ overview.health.open_tickets }}</strong>
            </div>
            <div>
              <span>SLA 超时</span><strong>{{ overview.health.overdue_tickets }}</strong>
            </div>
            <div>
              <span>可用积分</span><strong>{{ compact(overview.health.available_credits) }}</strong>
            </div>
            <div>
              <span>待释放积分</span><strong>{{ compact(overview.health.pending_credits) }}</strong>
            </div>
          </div>
        </article>
      </section>

      <section class="dashboard-grid dashboard-grid--bottom">
        <article class="panel">
          <header class="panel__head">
            <div>
              <h2>模型成本构成</h2>
              <p>按实际命中的供应商模型聚合</p>
            </div>
          </header>
          <ElTable :data="overview.model_cost_distribution" height="258" size="small">
            <ElTableColumn prop="model" label="模型" min-width="150" show-overflow-tooltip />
            <ElTableColumn label="用途" width="80"
              ><template #default="{ row }">{{
                row.usage_kind === "speech" ? "语音识别" : "对话"
              }}</template></ElTableColumn
            >
            <ElTableColumn prop="calls" label="调用" width="76" />
            <ElTableColumn label="成功率" width="86"
              ><template #default="{ row }"
                >{{ row.success_rate.toFixed(1) }}%</template
              ></ElTableColumn
            >
            <ElTableColumn label="成本" width="104" align="right"
              ><template #default="{ row }"
                >{{ row.unknown_cost_calls ? "≥ " : "" }}{{ money(row.cost_yuan, 4)
                }}<small v-if="row.unknown_cost_calls">（待确认）</small></template
              ></ElTableColumn
            >
          </ElTable>
        </article>
        <article class="panel risk-panel">
          <header class="panel__head">
            <div>
              <h2>需要处理</h2>
              <p>由当前真实状态自动识别，不是预设告警</p>
            </div>
            <ElTag v-if="overview.risks.length" type="warning" effect="plain"
              >{{ overview.risks.length }} 项</ElTag
            >
          </header>
          <div v-if="overview.risks.length" class="risk-list">
            <button
              v-for="risk in overview.risks"
              :key="risk.code"
              type="button"
              @click="openRisk(risk)"
            >
              <i :class="`risk-dot risk-dot--${risk.severity}`" />
              <span
                ><b>{{ risk.title }}</b
                ><small>{{ risk.description }}</small></span
              >
              <strong>{{ risk.count }}</strong>
              <FaSvgIcon v-if="risk.action_path" icon="ri:arrow-right-s-line" />
            </button>
          </div>
          <ElEmpty v-else :image-size="62" description="当前没有需要处理的经营风险" />
        </article>
      </section>

      <footer class="data-footnote">
        <span
          ><FaSvgIcon icon="ri:database-2-line" /> 数据源：{{
            overview.data_quality.sources.join("、")
          }}</span
        >
        <span
          >客户端事件 {{ integer(overview.data_quality.telemetry_events) }} 条 · 更新于
          {{ formatTime(overview.generated_at) }}</span
        >
      </footer>
    </template>
    <ElCard v-else-if="!currentApp" class="empty-card"
      ><ElEmpty description="请先在顶栏选择客户端"
    /></ElCard>
    <ElResult v-else icon="error" title="经营数据加载失败" sub-title="请检查网络后重试"
      ><template #extra
        ><ElButton type="primary" @click="load">重新加载</ElButton></template
      ></ElResult
    >
  </main>
</template>

<script setup lang="ts">
import dayjs from "dayjs";
import type { EChartsOption } from "@/plugins/echarts";
import OperationsOverviewAPI, {
  type OperationsOverview,
  type OverviewPeriodPreset,
  type OverviewQuery,
  type OverviewRisk,
} from "@/api/module_operations";
import FaECharts from "@/components/charts/fa-echarts/index.vue";
import { useClientAppStore, useSettingsStore } from "@stores";
import OverviewMetricCard from "./components/OverviewMetricCard.vue";

defineOptions({ name: "OperationsOverview" });

const router = useRouter();
const { currentApp } = storeToRefs(useClientAppStore());
const { isDark } = storeToRefs(useSettingsStore());
const periodPreset = ref<OverviewPeriodPreset>("last_30_days");
const customRange = ref<[string, string]>([
  dayjs().subtract(29, "day").format("YYYY-MM-DD"),
  dayjs().format("YYYY-MM-DD"),
]);
const periodOptions: { label: string; value: OverviewPeriodPreset }[] = [
  { label: "今天", value: "today" },
  { label: "昨天", value: "yesterday" },
  { label: "近 7 天", value: "last_7_days" },
  { label: "近 30 天", value: "last_30_days" },
  { label: "近 90 天", value: "last_90_days" },
  { label: "本月", value: "this_month" },
  { label: "上月", value: "last_month" },
  { label: "本季度", value: "this_quarter" },
  { label: "本年", value: "this_year" },
  { label: "自定义", value: "custom" },
];
const overview = ref<OperationsOverview>();
const loading = ref(false);
const loadFailed = ref(false);

const integer = (value: number) => Number(value || 0).toLocaleString("zh-CN");
const compact = (value: number) =>
  new Intl.NumberFormat("zh-CN", { notation: "compact", maximumFractionDigits: 1 }).format(
    value || 0
  );
const money = (value: number, digits = 2) =>
  `¥${Number(value || 0).toLocaleString("zh-CN", { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
const formatTime = (value: string) => dayjs(value).format("YYYY-MM-DD HH:mm");

const deltaRate = (value: number, previous: number) => {
  if (!previous) return value ? null : 0;
  return ((value - previous) / Math.abs(previous)) * 100;
};
const deltaText = (value: number, previous: number) => {
  const rate = deltaRate(value, previous);
  if (rate === null) return "上期无数据";
  if (Math.abs(rate) < 0.05) return "与上期持平";
  return `较上期 ${rate > 0 ? "+" : ""}${rate.toFixed(1)}%`;
};
const deltaTone = (value: number, previous: number): "positive" | "negative" | "neutral" => {
  const rate = deltaRate(value, previous);
  if (rate === null || Math.abs(rate) < 0.05) return "neutral";
  return rate > 0 ? "positive" : "negative";
};

const costDeltaTone = computed(() => {
  if (!overview.value) return "neutral";
  const rate = deltaRate(
    overview.value.summary.provider_cost_yuan,
    overview.value.previous.provider_cost_yuan
  );
  if (rate === null || Math.abs(rate) < 0.05) return "neutral";
  return rate < 0 ? "positive" : "negative";
});
const periodLabel = computed(() => overview.value?.period_label || "");
const costStatusLabel = computed(
  () =>
    ({
      reconciled: "已核对",
      partial: "部分核对",
      estimated: "含估算",
      actual_usage: "请求实算",
      incomplete: "成本待确认",
      no_data: "暂无调用",
    })[overview.value?.summary.cost_status || "no_data"]
);
const costStatusType = computed(() => {
  const status = overview.value?.summary.cost_status;
  if (status === "reconciled") return "success";
  if (status === "partial" || status === "estimated" || status === "incomplete") return "warning";
  return "info";
});
const disableFutureDate = (value: Date) => dayjs(value).isAfter(dayjs(), "day");
const handlePeriodChange = () => {
  if (periodPreset.value !== "custom") void load();
};
const chartTheme = computed(() => ({
  text: isDark.value ? "#a8b0bd" : "#667085",
  muted: isDark.value ? "#343b46" : "#e9edf3",
  tooltip: isDark.value ? "#1c2028" : "#ffffff",
}));
const axis = computed(() => ({
  axisLine: { lineStyle: { color: chartTheme.value.muted } },
  axisTick: { show: false },
  axisLabel: { color: chartTheme.value.text, fontSize: 11 },
  splitLine: { lineStyle: { color: chartTheme.value.muted } },
}));

const valueTrendOptions = computed<EChartsOption>(() => ({
  color: ["#3b82f6", "#f59e0b", "#8b5cf6", "#10b981"],
  tooltip: {
    trigger: "axis",
    backgroundColor: chartTheme.value.tooltip,
    borderColor: chartTheme.value.muted,
  },
  legend: { bottom: 0, textStyle: { color: chartTheme.value.text } },
  grid: { left: 18, right: 18, top: 22, bottom: 42, containLabel: true },
  xAxis: {
    type: "category",
    data: overview.value?.daily.map((item) => item.label || dayjs(item.date).format("MM/DD")) || [],
    ...axis.value,
    splitLine: { show: false },
  },
  yAxis: {
    type: "value",
    ...axis.value,
    axisLabel: { ...axis.value.axisLabel, formatter: (value: number) => `¥${compact(value)}` },
  },
  series: [
    {
      name: "净回款",
      type: "bar",
      barMaxWidth: 18,
      data: overview.value?.daily.map((item) => item.revenue_yuan) || [],
      itemStyle: { borderRadius: [4, 4, 0, 0] },
    },
    {
      name: "模型成本",
      type: "line",
      smooth: true,
      symbol: "none",
      data: overview.value?.daily.map((item) => item.provider_cost_yuan) || [],
    },
    {
      name: "供应商账单",
      type: "line",
      smooth: true,
      symbol: "none",
      lineStyle: { type: "dashed" },
      data: overview.value?.daily.map((item) => item.supplier_billed_cost_yuan) || [],
    },
    {
      name: "直接贡献",
      type: "line",
      smooth: true,
      symbol: "none",
      data: overview.value?.daily.map((item) => item.direct_margin_yuan) || [],
    },
  ],
}));

const userTrendOptions = computed<EChartsOption>(() => ({
  color: ["#3b82f6", "#8b5cf6", "#10b981"],
  tooltip: {
    trigger: "axis",
    backgroundColor: chartTheme.value.tooltip,
    borderColor: chartTheme.value.muted,
  },
  legend: { bottom: 0, textStyle: { color: chartTheme.value.text } },
  grid: { left: 18, right: 18, top: 18, bottom: 42, containLabel: true },
  xAxis: {
    type: "category",
    data: overview.value?.daily.map((item) => item.label || dayjs(item.date).format("MM/DD")) || [],
    ...axis.value,
    splitLine: { show: false },
  },
  yAxis: { type: "value", minInterval: 1, ...axis.value },
  series: [
    {
      name: "活跃用户",
      type: "line",
      smooth: true,
      showSymbol: false,
      areaStyle: { opacity: 0.08 },
      data: overview.value?.daily.map((item) => item.active_users) || [],
    },
    {
      name: "新增用户",
      type: "line",
      smooth: true,
      showSymbol: false,
      data: overview.value?.daily.map((item) => item.new_users) || [],
    },
    {
      name: "付费用户",
      type: "line",
      smooth: true,
      showSymbol: false,
      data: overview.value?.daily.map((item) => item.paid_users) || [],
    },
  ],
}));

const levelOptions = computed<EChartsOption>(() => ({
  color: ["#94a3b8", "#60a5fa", "#38bdf8", "#8b5cf6", "#f59e0b"],
  tooltip: {
    trigger: "item",
    formatter: "{b}<br/>{c} 人 · {d}%",
    backgroundColor: chartTheme.value.tooltip,
    borderColor: chartTheme.value.muted,
  },
  legend: {
    bottom: 0,
    itemWidth: 10,
    itemHeight: 10,
    textStyle: { color: chartTheme.value.text, fontSize: 10 },
  },
  series: [
    {
      type: "pie",
      radius: ["48%", "72%"],
      center: ["50%", "43%"],
      label: { show: false },
      itemStyle: { borderColor: chartTheme.value.tooltip, borderWidth: 3 },
      data:
        overview.value?.level_distribution.map((item) => ({
          name: item.name,
          value: item.count,
        })) || [],
    },
  ],
}));

const healthItems = computed(() => {
  if (!overview.value) return [];
  const health = overview.value.health;
  return [
    {
      label: "模型调用成功率",
      value: `${overview.value.summary.model_success_rate.toFixed(1)}%`,
      percentage: overview.value.summary.model_success_rate,
      tone: overview.value.summary.model_success_rate >= 95 ? "good" : "bad",
      status:
        overview.value.summary.model_success_rate >= 95
          ? ("success" as const)
          : ("exception" as const),
    },
    {
      label: "消息送达率",
      value: `${health.message_delivery_rate.toFixed(1)}%`,
      percentage: health.message_delivery_rate,
      tone: health.message_delivery_rate >= 95 ? "good" : "warn",
      status: health.message_delivery_rate >= 95 ? ("success" as const) : ("warning" as const),
    },
    {
      label: "消息已读率",
      value: `${health.message_read_rate.toFixed(1)}%`,
      percentage: health.message_read_rate,
      tone: "",
      status: undefined,
    },
    {
      label: "模型业务路由",
      value: `${health.active_model_routes} 条`,
      percentage: health.active_model_routes ? 100 : 0,
      tone: health.active_model_routes ? "good" : "bad",
      status: health.active_model_routes ? ("success" as const) : ("exception" as const),
    },
  ];
});

const funnelWidth = (count: number) => {
  const total = overview.value?.user_funnel[0]?.count || 0;
  return total ? Math.max(count ? 8 : 0, Math.round((count / total) * 100)) : 0;
};
const funnelConversion = (index: number) => {
  const items = overview.value?.user_funnel || [];
  const previous = items[index - 1]?.count || 0;
  const current = items[index]?.count || 0;
  return previous ? `${((current / previous) * 100).toFixed(1)}%` : "—";
};
const openRisk = (risk: OverviewRisk) => {
  if (risk.action_path) void router.push(risk.action_path);
};

async function load() {
  if (!currentApp.value) {
    overview.value = undefined;
    return;
  }
  loading.value = true;
  loadFailed.value = false;
  try {
    const query: OverviewQuery = { preset: periodPreset.value };
    if (periodPreset.value === "custom") {
      if (!customRange.value?.[0] || !customRange.value?.[1]) return;
      query.start_date = customRange.value[0];
      query.end_date = customRange.value[1];
    }
    const response = await OperationsOverviewAPI.get(query);
    overview.value = response.data.data;
    loadFailed.value = !overview.value;
  } catch {
    loadFailed.value = true;
  } finally {
    loading.value = false;
  }
}

watch(() => currentApp.value?.id, load, { immediate: true });
</script>

<style scoped>
.overview-page {
  min-height: 0;
  padding-bottom: 12px;
  overflow: auto;
}

.overview-header {
  display: flex;
  gap: 24px;
  align-items: center;
  justify-content: flex-end;
  padding: 0 2px 12px;
}

.overview-actions {
  display: flex;
  gap: 10px;
  align-items: center;
}

.panel h2 {
  margin: 0;
  color: var(--el-text-color-primary);
}

.panel__head p {
  margin: 5px 0 0;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.period-select {
  width: 126px;
}

.metric-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 12px;
}

.equation-card,
.panel {
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 12px;
}

.equation-card {
  display: flex;
  gap: 24px;
  align-items: center;
  justify-content: space-between;
  padding: 14px 18px;
  margin-top: 12px;
}

.equation-card__title {
  display: grid;
  gap: 3px;
}

.equation-card__title > span {
  font-size: 13px;
  font-weight: 700;
  color: var(--el-text-color-primary);
}

.equation-card__title small,
.equation-card__formula span {
  font-size: 11px;
  color: var(--el-text-color-secondary);
}

.equation-card__formula {
  display: flex;
  gap: 14px;
  align-items: center;
}

.equation-card__formula > div {
  display: grid;
  gap: 3px;
  min-width: 116px;
}

.equation-card__formula strong {
  font-size: 15px;
  color: var(--el-text-color-primary);
}

.equation-card__formula > b {
  font-weight: 400;
  color: var(--el-text-color-placeholder);
}

.equation-card__formula .formula-result strong {
  color: var(--el-color-success);
}

.dashboard-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.75fr) minmax(300px, 0.75fr);
  gap: 12px;
  margin-top: 12px;
}

.dashboard-grid--thirds {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.dashboard-grid--bottom {
  grid-template-columns: minmax(420px, 0.9fr) minmax(0, 1.1fr);
}

.panel {
  min-width: 0;
  padding: 16px;
}

.panel__head {
  display: flex;
  gap: 12px;
  align-items: flex-start;
  justify-content: space-between;
  min-height: 43px;
  margin-bottom: 8px;
}

.panel__head h2 {
  font-size: 14px;
}

.panel__head > span {
  font-size: 11px;
  color: var(--el-text-color-secondary);
}

.health-list {
  display: grid;
  gap: 17px;
  padding-top: 8px;
}

.health-list > div {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 7px 12px;
}

.health-list span {
  font-size: 12px;
  color: var(--el-text-color-regular);
}

.health-list strong {
  font-size: 12px;
  color: var(--el-text-color-primary);
}

.health-list :deep(.el-progress) {
  grid-column: 1 / -1;
}

.health-list .good {
  color: var(--el-color-success);
}

.health-list .warn {
  color: var(--el-color-warning);
}

.health-list .bad {
  color: var(--el-color-danger);
}

.funnel-list {
  display: grid;
  gap: 12px;
  padding-top: 4px;
}

.funnel-list > div > div:first-child,
.plan-list > div {
  display: flex;
  justify-content: space-between;
}

.funnel-list span,
.funnel-list small,
.plan-list small,
.service-grid span {
  font-size: 11px;
  color: var(--el-text-color-secondary);
}

.funnel-list strong,
.plan-list strong,
.service-grid strong {
  color: var(--el-text-color-primary);
}

.funnel-track {
  height: 6px;
  margin: 6px 0 4px;
  overflow: hidden;
  background: var(--el-fill-color);
  border-radius: 99px;
}

.funnel-track i {
  display: block;
  height: 100%;
  background: var(--el-color-primary);
  border-radius: inherit;
}

.plan-list {
  display: grid;
}

.plan-list > div {
  gap: 12px;
  align-items: center;
  padding: 13px 2px;
  border-bottom: 1px solid var(--el-border-color-lighter);
}

.plan-list > div:last-child {
  border-bottom: 0;
}

.plan-list span {
  display: grid;
  gap: 4px;
}

.plan-list b {
  font-size: 12px;
  color: var(--el-text-color-primary);
}

.service-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}

.service-grid > div {
  display: grid;
  gap: 7px;
  padding: 14px;
  background: var(--el-fill-color-lighter);
  border-radius: 9px;
}

.service-grid strong {
  font-size: 19px;
}

.risk-list {
  display: grid;
}

.risk-list button {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto auto;
  gap: 10px;
  align-items: center;
  width: 100%;
  padding: 12px 2px;
  color: inherit;
  text-align: left;
  cursor: pointer;
  background: transparent;
  border: 0;
  border-bottom: 1px solid var(--el-border-color-lighter);
}

.risk-list button:last-child {
  border-bottom: 0;
}

.risk-list button:hover b {
  color: var(--el-color-primary);
}

.risk-list span {
  display: grid;
  gap: 4px;
  min-width: 0;
}

.risk-list b,
.risk-list small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.risk-list b {
  font-size: 12px;
  color: var(--el-text-color-primary);
}

.risk-list small {
  font-size: 11px;
  color: var(--el-text-color-secondary);
}

.risk-list strong {
  font-size: 13px;
  color: var(--el-text-color-primary);
}

.risk-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
}

.risk-dot--critical {
  background: var(--el-color-danger);
}

.risk-dot--warning {
  background: var(--el-color-warning);
}

.risk-dot--info {
  background: var(--el-color-primary);
}

.data-footnote {
  display: flex;
  gap: 16px;
  justify-content: space-between;
  padding: 12px 4px 0;
  font-size: 11px;
  color: var(--el-text-color-placeholder);
}

.data-footnote span {
  display: flex;
  gap: 6px;
  align-items: center;
}

.empty-card {
  min-height: 360px;
}

@media (width <= 1400px) {
  .metric-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .dashboard-grid--thirds {
    grid-template-columns: 1fr 1fr;
  }
}

@media (width <= 960px) {
  .overview-header,
  .equation-card,
  .data-footnote {
    flex-direction: column;
    align-items: flex-start;
  }

  .metric-grid,
  .dashboard-grid,
  .dashboard-grid--thirds,
  .dashboard-grid--bottom {
    grid-template-columns: 1fr 1fr;
  }

  .panel--wide {
    grid-column: 1 / -1;
  }
}

@media (width <= 640px) {
  .overview-actions,
  .equation-card__formula {
    flex-direction: column;
    align-items: stretch;
    width: 100%;
  }

  .metric-grid,
  .dashboard-grid,
  .dashboard-grid--thirds,
  .dashboard-grid--bottom {
    grid-template-columns: 1fr;
  }

  .panel--wide {
    grid-column: auto;
  }
}
</style>
