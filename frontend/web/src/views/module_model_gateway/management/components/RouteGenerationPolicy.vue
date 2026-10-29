<template>
  <section class="generation-policy" aria-label="生成与费用预算">
    <div class="policy-heading">
      <div>
        <strong>生成与费用预算</strong>
        <p>同时限制回答、思考和总耗时，按完整预算预占费用。</p>
      </div>
      <ElSwitch
        :model-value="Boolean(modelValue)"
        aria-label="启用生成预算"
        @update:model-value="toggleBudget"
      />
    </div>
    <p v-if="!modelValue" class="policy-hint">
      当前沿用供应商默认生成方式，回答上限不一定包含思考消耗。
    </p>
    <template v-else>
      <p class="policy-hint">
        适用于已支持的 Qwen3.8 文本模型；主模型、备用模型和用户选择的模型均需兼容。
        此策略暂不支持图片或文件直接输入。
      </p>
      <div class="policy-heading thinking-heading">
        <label>启用思考</label>
        <ElSwitch
          :model-value="modelValue.enable_thinking"
          aria-label="启用思考"
          @update:model-value="toggleThinking"
        />
      </div>
      <div class="policy-fields">
        <ElFormItem label="思考预算（Token）">
          <ElInputNumber
            :model-value="modelValue.thinking_budget_tokens"
            :min="modelValue.enable_thinking ? 1 : 0"
            :max="262144"
            :precision="0"
            :disabled="!modelValue.enable_thinking"
            aria-label="思考预算"
            @update:model-value="setNumber('thinking_budget_tokens', $event)"
          />
        </ElFormItem>
        <ElFormItem label="整次处理时限（秒）">
          <ElInputNumber
            :model-value="modelValue.total_timeout_seconds"
            :min="1"
            :max="1800"
            :precision="0"
            aria-label="整次处理时限"
            @update:model-value="setNumber('total_timeout_seconds', $event)"
          />
        </ElFormItem>
      </div>
      <ElFormItem label="回答格式">
        <ElSelect
          :model-value="modelValue.response_format"
          aria-label="回答格式"
          @update:model-value="setFormat"
        >
          <ElOption label="由任务提示决定" value="text" />
          <ElOption label="JSON 对象" value="json_object" />
        </ElSelect>
      </ElFormItem>
      <p class="policy-hint">
        回答最多 {{ answerLimit.toLocaleString() }} Token，思考最多
        {{ modelValue.thinking_budget_tokens.toLocaleString() }} Token。
        整次时限包含备用模型尝试；余额不足完整预算时不会开始生成。
      </p>
      <p v-if="modelValue.response_format === 'json_object'" class="policy-hint">
        使用此格式的任务提示须明确要求 JSON；不适合直接套用到自由聊天。
      </p>
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed } from "vue";
import type { GenerationSettings } from "@/api/module_model_gateway";

const props = defineProps<{
  modelValue: GenerationSettings | null;
  maxOutputTokens?: number;
}>();
const emit = defineEmits<{ "update:modelValue": [value: GenerationSettings | null] }>();
const answerLimit = computed(() => props.maxOutputTokens || 0);

function toggleBudget(enabled: string | number | boolean) {
  emit(
    "update:modelValue",
    enabled
      ? {
          policy_version: "qwen3.8-bounded-v1",
          enable_thinking: true,
          thinking_budget_tokens: 4096,
          total_timeout_seconds: 600,
          response_format: "text",
        }
      : null
  );
}

function toggleThinking(enabled: string | number | boolean) {
  if (!props.modelValue) return;
  emit("update:modelValue", {
    ...props.modelValue,
    enable_thinking: Boolean(enabled),
    thinking_budget_tokens: enabled ? Math.max(props.modelValue.thinking_budget_tokens, 4096) : 0,
  });
}

function setNumber(
  key: "thinking_budget_tokens" | "total_timeout_seconds",
  value: number | undefined
) {
  if (!props.modelValue || value === undefined) return;
  emit("update:modelValue", { ...props.modelValue, [key]: value });
}

function setFormat(value: string) {
  if (!props.modelValue || (value !== "text" && value !== "json_object")) return;
  emit("update:modelValue", { ...props.modelValue, response_format: value });
}
</script>

<style scoped lang="scss">
.generation-policy {
  margin: 16px 0;
  padding: 16px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: var(--el-border-radius-base);
}
.policy-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  p {
    margin: 6px 0 0;
    color: var(--el-text-color-secondary);
    font-size: 12px;
  }
}
.policy-hint {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  line-height: 1.7;
}
.thinking-heading {
  margin: 16px 0;
}
.policy-fields {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}
@media (max-width: 480px) {
  .policy-fields {
    grid-template-columns: 1fr;
    gap: 0;
  }
}
</style>
