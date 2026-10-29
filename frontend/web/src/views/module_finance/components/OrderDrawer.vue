<script setup lang="ts">
import { billingModeLabel, modeSwitchLabel } from "@/api/module_client/app";
import { ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useClientAppStore } from "@stores";
import API, { type OrderDetail } from "@/api/module_finance";
import { dateTime, money, providerName, statusText } from "../shared";
import AuditTrail from "./AuditTrail.vue";
const creditStatus: Record<string, string> = {
  pending: "待释放",
  released: "已释放",
  expired: "已失效",
  refunded: "退款终止",
  mode_reset: "切换模式失效",
};
const props = defineProps<{ orderId: number | null }>();
const open = defineModel<boolean>({ required: true });
const detail = ref<OrderDetail | null>(null),
  loading = ref(false),
  failed = ref(false);
const { currentApp } = storeToRefs(useClientAppStore());
let generation = 0;
async function load() {
  const stamp = ++generation;
  detail.value = null;
  if (!props.orderId || !open.value) return;
  loading.value = true;
  failed.value = false;
  try {
    const data = (await API.order(props.orderId)).data.data;
    if (stamp === generation) detail.value = data;
  } catch {
    if (stamp === generation) failed.value = true;
  } finally {
    if (stamp === generation) loading.value = false;
  }
}
watch([open, () => props.orderId], load);
watch(
  () => currentApp.value?.id,
  () => {
    generation++;
    open.value = false;
    detail.value = null;
  }
);
</script>
<template>
  <ElDrawer v-model="open" title="交易详情" size="min(960px,96vw)" destroy-on-close>
    <ElSkeleton v-if="loading" :rows="12" animated />
    <ElResult v-else-if="failed" icon="error" title="订单详情加载失败"
      ><template #extra><ElButton @click="load">重试</ElButton></template></ElResult
    >
    <template v-else-if="detail"
      ><ElDescriptions :column="2" border
        ><ElDescriptionsItem label="商户订单号" :span="2">{{
          detail.order.order_no
        }}</ElDescriptionsItem
        ><ElDescriptionsItem label="渠道交易号" :span="2">{{
          detail.order.provider_trade_no || "—"
        }}</ElDescriptionsItem
        ><ElDescriptionsItem label="用户"
          >{{ detail.order.display_name || detail.order.username }} · #{{
            detail.order.user_id
          }}</ElDescriptionsItem
        ><ElDescriptionsItem label="支付渠道">{{
          providerName(detail.order.provider)
        }}</ElDescriptionsItem
        ><ElDescriptionsItem label="商品">{{ detail.order.product_name }}</ElDescriptionsItem
        ><ElDescriptionsItem
          v-if="detail.plan_snapshot.entitlement_kind === 'duration'"
          label="购买时长"
          >{{ detail.plan_snapshot.benefit_period_days }} 天</ElDescriptionsItem
        ><ElDescriptionsItem label="权益类型">{{
          billingModeLabel(detail.order.entitlement_kind ?? "credits")
        }}</ElDescriptionsItem
        ><ElDescriptionsItem label="切换状态">{{
          modeSwitchLabel(detail.order.mode_switch?.status)
        }}</ElDescriptionsItem
        ><ElDescriptionsItem label="支付状态">{{
          statusText(detail.order.status)
        }}</ElDescriptionsItem
        ><ElDescriptionsItem label="订单金额">{{
          money(detail.order.amount_fen)
        }}</ElDescriptionsItem
        ><ElDescriptionsItem label="累计退款">{{
          money(detail.order.refunded_fen)
        }}</ElDescriptionsItem
        ><ElDescriptionsItem label="退款占用">{{
          money(detail.order.refund_reserved_fen)
        }}</ElDescriptionsItem
        ><ElDescriptionsItem label="可退余额">{{
          money(detail.order.refundable_fen)
        }}</ElDescriptionsItem
        ><ElDescriptionsItem label="创建时间">{{
          dateTime(detail.order.created_time)
        }}</ElDescriptionsItem
        ><ElDescriptionsItem label="支付时间">{{
          dateTime(detail.order.paid_at)
        }}</ElDescriptionsItem
        ><ElDescriptionsItem label="支付到期">{{
          dateTime(detail.order.expires_at)
        }}</ElDescriptionsItem
        ><ElDescriptionsItem label="关闭时间">{{
          dateTime(detail.order.closed_at)
        }}</ElDescriptionsItem
        ><ElDescriptionsItem v-if="detail.order.failure_reason" label="失败原因" :span="2">{{
          detail.order.failure_reason
        }}</ElDescriptionsItem></ElDescriptions
      >
      <ElTabs class="detail-tabs"
        ><ElTabPane label="权益明细"
          ><ElTable :data="detail.cycles"
            ><ElTableColumn prop="id" label="订阅周期ID" /><ElTableColumn
              label="开始时间"
              min-width="160"
              ><template #default="{ row }">{{ dateTime(row.starts_at) }}</template></ElTableColumn
            ><ElTableColumn label="结束时间" min-width="160"
              ><template #default="{ row }">{{ dateTime(row.ends_at) }}</template></ElTableColumn
            ><ElTableColumn label="状态"
              ><template #default="{ row }">{{
                row.status === "refunded"
                  ? "退款终止"
                  : row.status === "active"
                    ? "生效"
                    : row.status
              }}</template></ElTableColumn
            ></ElTable
          >
          <ElTable
            v-if="detail.plan_snapshot.entitlement_kind !== 'duration'"
            :data="detail.credits"
            ><ElTableColumn prop="id" label="积分批次ID" /><ElTableColumn
              prop="amount"
              label="发放数量"
            /><ElTableColumn prop="available" label="当前可用" /><ElTableColumn
              prop="reserved"
              label="使用中预留"
            /><ElTableColumn label="批次状态"
              ><template #default="{ row }">{{
                creditStatus[row.status] || row.status
              }}</template></ElTableColumn
            ><ElTableColumn label="失效时间" min-width="170"
              ><template #default="{ row }">{{ dateTime(row.expires_at) }}</template></ElTableColumn
            ></ElTable
          ></ElTabPane
        >
        <ElTabPane label="退款流水"
          ><ElTable :data="detail.refunds"
            ><ElTableColumn prop="refund_no" label="退款单号" min-width="210" /><ElTableColumn
              label="退款金额"
              width="130"
              ><template #default="{ row }">{{ money(row.amount_fen) }}</template></ElTableColumn
            ><ElTableColumn prop="reason" label="退款原因" min-width="180" /><ElTableColumn
              label="退款完成时间"
              min-width="170"
              ><template #default="{ row }">{{
                dateTime(row.refunded_at)
              }}</template></ElTableColumn
            ></ElTable
          ></ElTabPane
        >
        <ElTabPane label="推广奖励"
          ><ElTable :data="detail.rewards"
            ><ElTableColumn prop="user_id" label="获奖用户ID" /><ElTableColumn label="资产类型"
              ><template #default="{ row }">{{
                row.asset === "cash" ? "佣金" : "积分"
              }}</template></ElTableColumn
            ><ElTableColumn label="奖励数额"
              ><template #default="{ row }">{{
                row.asset === "cash" ? money(row.amount) : row.amount
              }}</template></ElTableColumn
            ><ElTableColumn label="已冲正"
              ><template #default="{ row }">{{
                row.asset === "cash" ? money(row.reversed_amount) : row.reversed_amount
              }}</template></ElTableColumn
            ><ElTableColumn prop="status" label="状态" /></ElTable
        ></ElTabPane>
        <ElTabPane label="支付与通知"
          ><ElTable :data="detail.attempts"
            ><ElTableColumn prop="action" label="请求动作" /><ElTableColumn label="状态"
              ><template #default="{ row }">{{ statusText(row.status) }}</template></ElTableColumn
            ><ElTableColumn prop="error_message" label="处理信息" min-width="200" /><ElTableColumn
              label="时间"
              min-width="170"
              ><template #default="{ row }">{{
                dateTime(row.created_time)
              }}</template></ElTableColumn
            ></ElTable
          ><ElTable :data="detail.callbacks"
            ><ElTableColumn label="通知状态"
              ><template #default="{ row }">{{ statusText(row.status) }}</template></ElTableColumn
            ><ElTableColumn prop="failure_reason" label="处理信息" min-width="200" /><ElTableColumn
              label="核验时间"
              min-width="170"
              ><template #default="{ row }">{{
                dateTime(row.verified_at)
              }}</template></ElTableColumn
            ></ElTable
          ></ElTabPane
        >
        <ElTabPane label="操作记录"><AuditTrail :rows="detail.audits" /></ElTabPane></ElTabs
    ></template>
  </ElDrawer>
</template>
<style scoped>
.detail-tabs {
  margin-top: 24px;
}
.el-table + .el-table {
  margin-top: 20px;
}
</style>
