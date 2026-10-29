<script setup lang="ts">
import type { SpeechPricing } from "@/api/module_model_gateway";
const protocol = defineModel<string | null>("protocol");
const pricing = defineModel<SpeechPricing | null>("pricing");
const protocols: [string, string][] = [
  ["openai_transcriptions", "通用语音转写（OpenAI 兼容）"],
  ["qwen_asr", "千问 ASR（Chat Completions）"],
  ["qwen_realtime", "千问 ASR Realtime"],
  ["dashscope_asr", "百炼同步识别（Qwen Audio / Fun-ASR）"],
  ["dashscope_realtime", "百炼流式识别（Fun-ASR / Paraformer）"],
];
function addPrice() {
  if (!pricing.value)
    pricing.value = {
      region: "",
      currency: "CNY",
      verified_at: new Date().toISOString().slice(0, 10),
      source_url: null,
      note: "",
      items: [],
    };
  pricing.value.items.push({ label: "音频输入", unit: "second", price: "" });
}
function markManual() {
  if (pricing.value) {
    pricing.value.source_url = null;
    pricing.value.verified_at = new Date().toISOString().slice(0, 10);
  }
}
</script>
<template>
  <ElDivider content-position="left">语音能力与采购价</ElDivider>
  <ElFormItem label="语音识别接口">
    <ElSelect
      v-model="protocol"
      clearable
      placeholder="无需语音识别时留空"
      @clear="protocol = null"
    >
      <ElOption v-for="[value, label] in protocols" :key="value" :value="value" :label="label" />
    </ElSelect>
    <small
      >不限模型名称和数量；新增型号选择其兼容协议即可接入。语音合成及全模态对话不等于语音转写，请按供应商文档选择。</small
    >
  </ElFormItem>
  <div v-if="pricing" @change="markManual">
    <ElFormItem label="价格适用地域"
      ><ElInput v-model="pricing.region" placeholder="与供应商账号地域一致"
    /></ElFormItem>
    <div v-for="(item, index) in pricing.items" :key="index" class="price-row">
      <ElInput v-model="item.label" aria-label="计费项目" placeholder="计费项目" />
      <ElInput v-model="item.price" type="number" min="0" aria-label="采购单价" />
      <ElSelect v-model="item.unit" aria-label="计费单位">
        <ElOption label="元 / 秒" value="second" /><ElOption
          label="元 / 万字符"
          value="10k_characters"
        />
        <ElOption label="元 / 百万 Token" value="million_tokens" /><ElOption
          label="元 / 音色"
          value="voice"
        />
      </ElSelect>
      <ElButton
        link
        type="danger"
        @click="
          pricing.items.splice(index, 1);
          markManual();
        "
        >删除</ElButton
      >
    </div>
    <ElFormItem label="计费说明"><ElInput v-model="pricing.note" type="textarea" /></ElFormItem>
  </div>
  <ElButton
    @click="
      addPrice();
      markManual();
    "
    >添加语音计费项</ElButton
  >
  <small>语音识别启用前须有采购价。手动调整后标记为人工核价，不再冒用官方来源。</small>
</template>
<style scoped>
small {
  display: block;
  width: 100%;
  margin: 6px 0;
  color: var(--el-text-color-secondary);
  line-height: 1.6;
}
.price-row {
  display: grid;
  grid-template-columns: 2fr 1fr 1.5fr auto;
  gap: 8px;
  margin-bottom: 12px;
}
@media (max-width: 600px) {
  .price-row {
    grid-template-columns: 1fr 1fr;
  }
}
</style>
