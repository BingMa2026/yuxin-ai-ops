<script setup lang="ts">
import { ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useClientAppStore } from "@stores";
import API, { type Order, type RefundPreview } from "@/api/module_finance";
import RefundImpact from "./RefundImpact.vue";
import { money } from "../shared";
const props = defineProps<{ order: Order | null }>();
const open = defineModel<boolean>({ required: true });
const emit = defineEmits<{ saved: [] }>();
const { currentApp } = storeToRefs(useClientAppStore());
const amount = ref(0),
  reason = ref(""),
  action = ref<"retain" | "terminate" | "">(""),
  busy = ref(false),
  idempotency = ref("");
const preview = ref<RefundPreview | null>(null),
  previewLoading = ref(false),
  previewFailed = ref(false);
let previewGeneration = 0;
async function loadPreview() {
  const stamp = ++previewGeneration;
  preview.value = null;
  previewFailed.value = false;
  if (!open.value || !props.order || !action.value) return;
  previewLoading.value = true;
  try {
    const result = (await API.refundPreview(props.order.id, action.value)).data.data;
    if (stamp === previewGeneration) preview.value = result;
  } catch {
    if (stamp === previewGeneration) previewFailed.value = true;
  } finally {
    if (stamp === previewGeneration) previewLoading.value = false;
  }
}
watch([open, action, () => props.order?.id], loadPreview, { flush: "post" });
watch(open, (value) => {
  if (value) {
    amount.value = (props.order?.refundable_fen || 0) / 100;
    reason.value = "";
    action.value = "";
    idempotency.value = crypto.randomUUID();
  }
});
watch(
  () => currentApp.value?.id,
  () => {
    open.value = false;
  }
);
async function submit() {
  if (
    !action.value ||
    !props.order ||
    busy.value ||
    !preview.value ||
    reason.value.trim().length < 2
  )
    return;
  busy.value = true;
  const scope = currentApp.value?.id;
  try {
    await API.createRefund({
      order_id: props.order.id,
      amount_fen: Math.round(amount.value * 100),
      reason: reason.value.trim(),
      entitlement_action: action.value,
      idempotency_key: idempotency.value,
      preview_token: preview.value.preview_token,
    });
    if (scope === currentApp.value?.id) {
      open.value = false;
      emit("saved");
    }
  } catch {
    if (scope === currentApp.value?.id) await loadPreview();
  } finally {
    busy.value = false;
  }
}
</script>
<template>
  <ElDialog v-model="open" title="申请退款" width="min(600px,94vw)" :close-on-click-modal="!busy">
    <ElDescriptions v-if="order" :column="1" border
      ><ElDescriptionsItem label="原支付订单">{{ order.order_no }}</ElDescriptionsItem
      ><ElDescriptionsItem label="用户"
        >{{ order.display_name || order.username }} · #{{ order.user_id }}</ElDescriptionsItem
      ><ElDescriptionsItem label="商品">{{ order.product_name }}</ElDescriptionsItem
      ><ElDescriptionsItem label="支付 / 已退 / 可退"
        >{{ money(order.amount_fen) }} / {{ money(order.refunded_fen) }} /
        {{ money(order.refundable_fen) }}</ElDescriptionsItem
      ></ElDescriptions
    >
    <ElForm label-position="top" class="refund-form"
      ><ElFormItem label="本次退款金额（元）" required
        ><ElInputNumber
          v-model="amount"
          :min="0.01"
          :max="(order?.refundable_fen || 0) / 100"
          :precision="2"
          :step="1" /></ElFormItem
      ><ElFormItem label="退款类型（请明确选择）" required
        ><ElRadioGroup v-model="action" :disabled="busy"
          ><ElRadio value="retain">补偿退款 · 保留订阅与积分</ElRadio
          ><ElRadio value="terminate">退订退款 · 终止该订单剩余权益</ElRadio></ElRadioGroup
        ></ElFormItem
      ><ElAlert
        v-if="action"
        :title="
          action === 'terminate'
            ? preview?.entitlement_kind === 'duration'
              ? '退款成功后，终止该订单剩余使用时长，其他续费订单时长保留并前移衔接。'
              : '退款成功后，收回该订单剩余可用积分、停止未释放积分和对应订阅权益。已消费部分保留记录，其他订单权益不受影响。'
            : '本次只退还款项，订阅和积分权益继续保留。'
        "
        :type="action === 'terminate' ? 'warning' : 'info'"
        :closable="false" />
      <ElSkeleton v-if="previewLoading" :rows="4" animated />
      <ElAlert
        v-else-if="previewFailed"
        title="权益预览加载失败，请刷新后再提交"
        type="error"
        :closable="false"
      >
        <ElButton link type="primary" @click="loadPreview">重新加载</ElButton>
      </ElAlert>
      <RefundImpact v-else-if="preview" :preview="preview" />
      <ElFormItem label="退款依据" required
        ><ElInput
          v-model="reason"
          type="textarea"
          :rows="3"
          maxlength="500"
          show-word-limit
          placeholder="填写客户诉求、政策依据或关联工单号" /></ElFormItem
    ></ElForm>
    <template #footer
      ><ElButton :disabled="busy" @click="open = false">取消</ElButton
      ><ElButton
        type="primary"
        :loading="busy"
        :disabled="
          !preview ||
          previewLoading ||
          reason.trim().length < 2 ||
          !amount ||
          amount * 100 > (order?.refundable_fen || 0)
        "
        @click="submit"
        >提交审核</ElButton
      ></template
    >
  </ElDialog>
</template>
<style scoped>
.refund-form {
  margin-top: 20px;
}
.el-alert {
  margin-bottom: 16px;
}
</style>
