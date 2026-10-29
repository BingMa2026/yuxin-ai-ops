<script setup lang="ts">
import type { RightsPolicy } from "@/api/module_growth";
const model = defineModel<RightsPolicy>({ required: true });
const limits: {
  key:
    | "withdrawal_min_fen"
    | "withdrawal_max_fen"
    | "withdrawal_daily_fen"
    | "withdrawal_monthly_fen";
  label: string;
}[] = [
  { key: "withdrawal_min_fen", label: "单次最低（元）" },
  { key: "withdrawal_max_fen", label: "单次最高（元）" },
  { key: "withdrawal_daily_fen", label: "每日金额上限（元）" },
  { key: "withdrawal_monthly_fen", label: "每月金额上限（元）" },
];
</script>
<template>
  <ElForm label-position="top">
    <ElAlert
      title="积分用于消费；推广现金用于提现。具体奖励数量和比例在激励规则中维护。"
      :closable="false"
      type="info"
      style="margin-bottom: 20px"
    />
    <section class="growth-form-section">
      <header><FaSvgIcon icon="ri:coin-line" />积分权益</header>
      <div class="growth-form-grid">
        <ElFormItem label="奖励积分有效期（天）"
          ><ElInputNumber v-model="model.credit_valid_days" :min="1" :max="3650"
        /></ElFormItem>
        <ElFormItem label="允许转赠"><ElSwitch v-model="model.gift_enabled" /></ElFormItem>
        <ElFormItem label="允许转赠奖励积分"
          ><ElSwitch v-model="model.gift_reward_credits"
        /></ElFormItem>
        <ElFormItem label="接收方需有效订阅"
          ><ElSwitch v-model="model.gift_requires_subscription"
        /></ElFormItem>
        <ElFormItem label="单次转赠最低积分"
          ><ElInputNumber v-model="model.gift_minimum" :min="1"
        /></ElFormItem>
        <ElFormItem label="每日转赠次数"
          ><ElInputNumber v-model="model.gift_daily_count" :min="1" :max="100"
        /></ElFormItem>
        <ElFormItem label="月初可赠余额比例（%）"
          ><ElInputNumber v-model="model.gift_monthly_percent" :min="1" :max="100"
        /></ElFormItem>
      </div>
    </section>
    <section class="growth-form-section">
      <header><FaSvgIcon icon="ri:wallet-3-line" />推广现金权益</header>
      <div class="growth-form-grid">
        <ElFormItem label="开放提现"><ElSwitch v-model="model.withdrawal_enabled" /></ElFormItem>
        <ElFormItem label="每日提现次数"
          ><ElInputNumber v-model="model.withdrawal_daily_count" :min="1" :max="100"
        /></ElFormItem>
        <ElFormItem v-for="limit in limits" :key="limit.key" :label="limit.label"
          ><ElInputNumber
            :model-value="model[limit.key] / 100"
            :min="1"
            :precision="2"
            @update:model-value="model[limit.key] = Math.round(($event || 0) * 100)"
        /></ElFormItem>
      </div>
    </section>
    <ElText type="info">提现还需商户转账能力就绪及财务审核；发布权益政策不会直接发起打款。</ElText>
  </ElForm>
</template>
