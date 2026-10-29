<script setup lang="ts">
import type { RefundPreview } from "@/api/module_finance";
import { dateTime } from "../shared";
defineProps<{ preview: RefundPreview }>();
</script>
<template>
  <div class="refund-impact">
    <ElDescriptions :column="1" border>
      <ElDescriptionsItem label="当前套餐">{{ preview.before.plan_name }}</ElDescriptionsItem>
      <ElDescriptionsItem label="当前到期时间">{{
        dateTime(preview.before.ends_at)
      }}</ElDescriptionsItem>
      <ElDescriptionsItem label="退款后套餐">{{ preview.after.plan_name }}</ElDescriptionsItem>
      <ElDescriptionsItem label="退款后到期时间">{{
        dateTime(preview.after.ends_at)
      }}</ElDescriptionsItem>
      <ElDescriptionsItem v-if="preview.entitlement_kind !== 'duration'" label="回收可用积分">{{
        preview.revoked_available.toLocaleString()
      }}</ElDescriptionsItem>
      <ElDescriptionsItem v-if="preview.entitlement_kind !== 'duration'" label="取消待发放积分">{{
        preview.cancelled_pending.toLocaleString()
      }}</ElDescriptionsItem>
      <ElDescriptionsItem v-if="preview.entitlement_kind !== 'duration'" label="在途预留积分">{{
        preview.reserved_at_refund.toLocaleString()
      }}</ElDescriptionsItem>
      <ElDescriptionsItem v-if="preview.superseded_credits" label="升级已取消发放积分">{{
        preview.superseded_credits.toLocaleString()
      }}</ElDescriptionsItem>
      <ElDescriptionsItem v-if="preview.entitlement_kind !== 'duration'" label="已消费或过期积分">{{
        preview.consumed_or_expired.toLocaleString()
      }}</ElDescriptionsItem>
    </ElDescriptions>
    <p class="text-g-500 text-xs mt-2">
      {{
        preview.entitlement_kind === "duration"
          ? "渠道确认退款成功后，终止该订单剩余使用时长，后续续费时长前移衔接。已使用时长不追扣。部分退款选择终止权益，也会终止该订单全部剩余时长。"
          : "仅在渠道确认退款成功后处理权益。此处按当前状态预估；在途用量正常结算，已消费积分不自动追扣。部分退款选择终止权益，也会终止该订单全部剩余权益。"
      }}
    </p>
  </div>
</template>
<style scoped>
.refund-impact {
  margin: 16px 0;
}
</style>
