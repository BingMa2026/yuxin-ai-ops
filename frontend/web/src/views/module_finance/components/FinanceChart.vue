<script setup lang="ts">
import { nextTick, onMounted, watch } from "vue";
import { useChart } from "@/hooks/core/useChart";
import { getCssVar } from "@utils";
import type { EChartsOption } from "echarts";
import type { Overview } from "@/api/module_finance";
import { money, providerName } from "../shared";
const props = defineProps<{ data: Overview; kind: "trend" | "channel" }>();
const {
  chartRef,
  initChart,
  isDark,
  getTooltipStyle,
  getAxisLabelStyle,
  getSplitLineStyle,
  getLegendStyle,
} = useChart();
function draw() {
  const colors = [
    getCssVar("--el-color-primary"),
    getCssVar("--el-color-warning"),
    getCssVar("--el-color-success"),
  ] as const;
  let option: EChartsOption;
  if (props.kind === "trend")
    option = {
      color: [...colors],
      tooltip: getTooltipStyle("axis", { valueFormatter: (v: number) => `¥${v.toFixed(2)}` }),
      legend: { ...getLegendStyle("bottom"), data: ["支付收款", "退款", "推广支出"] },
      grid: { left: 18, right: 18, top: 30, bottom: 50, containLabel: true },
      xAxis: {
        type: "category",
        boundaryGap: false,
        data: props.data.daily.map((r) => r.date.slice(5)),
        axisLabel: getAxisLabelStyle(),
        axisLine: { show: false },
        axisTick: { show: false },
      },
      yAxis: {
        type: "value",
        name: "元",
        axisLabel: getAxisLabelStyle(),
        splitLine: getSplitLineStyle(),
      },
      series: [
        ["received_fen", "支付收款"],
        ["refund_fen", "退款"],
        ["payout_fen", "推广支出"],
      ].map(([key, name]) => ({
        name,
        type: "line",
        smooth: 0.2,
        showSymbol: props.data.daily.length < 10,
        symbolSize: 6,
        lineStyle: { width: 3 },
        data: props.data.daily.map((r) => Number(r[key as keyof typeof r]) / 100),
      })),
    };
  else
    option = {
      color: [colors[0], colors[2]],
      tooltip: getTooltipStyle("item", { valueFormatter: (v: number) => `¥${v.toFixed(2)}` }),
      legend: { show: false },
      series: [
        {
          type: "pie",
          stillShowZeroSum: false,
          radius: ["57%", "78%"],
          center: ["50%", "44%"],
          avoidLabelOverlap: true,
          label: { show: false },
          itemStyle: { borderWidth: 4, borderColor: getCssVar("--el-bg-color"), borderRadius: 5 },
          data: props.data.channels.map((c) => ({
            name: providerName(c.provider),
            value: c.received_fen / 100,
            itemStyle: { color: c.provider === "alipay" ? colors[0] : colors[2] },
          })),
          emphasis: {
            label: {
              show: true,
              formatter: "{b}\n{d}%",
              fontSize: 16,
              color: getCssVar("--el-text-color-primary"),
            },
          },
        },
      ],
    };
  initChart(option);
}
onMounted(() => nextTick(draw));
watch([() => props.data, isDark], () => nextTick(draw), { deep: true });
</script>
<template>
  <div class="chart-panel" :class="{ 'channel-chart': kind === 'channel' }">
    <div
      ref="chartRef"
      class="finance-chart"
      :aria-label="kind === 'trend' ? '收款退款和推广支出趋势' : '支付渠道收款占比'"
    />
    <div v-if="kind === 'channel'" class="channel-legend">
      <div v-for="channel in data.channels" :key="channel.provider">
        <span><i :class="channel.provider" />{{ providerName(channel.provider) }}</span>
        <strong>{{ money(channel.received_fen) }}</strong>
      </div>
    </div>
  </div>
</template>
<style scoped>
.finance-chart {
  height: 320px;
  width: 100%;
}
.channel-chart .finance-chart {
  height: 260px;
}
.channel-legend {
  display: grid;
  gap: 8px;
  padding: 0 16px;
  font-size: 12px;
  color: var(--el-text-color-regular);
}
.channel-legend > div,
.channel-legend span {
  display: flex;
  align-items: center;
  gap: 8px;
  justify-content: space-between;
}
.channel-legend i {
  width: 8px;
  height: 8px;
  border-radius: 2px;
  background: var(--el-color-primary);
}
.channel-legend i.wechat {
  background: var(--el-color-success);
}
</style>
