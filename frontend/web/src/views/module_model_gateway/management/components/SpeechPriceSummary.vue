<script setup lang="ts">
import type { SpeechPricing } from "@/api/module_model_gateway";
defineProps<{ pricing?: SpeechPricing | null }>();
const units = {
  second: "元 / 秒",
  "10k_characters": "元 / 万字符",
  million_tokens: "元 / 百万 Token",
  voice: "元 / 音色",
};
</script>
<template>
  <div v-if="pricing" class="speech-price">
    <span v-for="(item, index) in pricing.items" :key="index"
      >{{ item.label }} <b>{{ item.price }}</b> {{ units[item.unit] }}</span
    >
    <small
      >{{ pricing.region }} · {{ pricing.verified_at }} 核价
      <a
        v-if="pricing.source_url"
        :href="pricing.source_url"
        target="_blank"
        rel="noopener noreferrer"
        >价格来源</a
      >
    </small>
    <ElTooltip v-if="pricing.note" :content="pricing.note"><small>计费说明 ⓘ</small></ElTooltip>
  </div>
  <ElTag v-else type="warning" size="small">语音价格待配置</ElTag>
</template>
<style scoped>
.speech-price {
  display: flex;
  flex-wrap: wrap;
  gap: 5px 18px;
  font-size: 12px;
  line-height: 1.65;
  padding: 4px 0;
}
.speech-price small {
  color: var(--el-text-color-secondary);
}
.speech-price a {
  color: var(--el-color-primary);
  margin-left: 8px;
}
</style>
