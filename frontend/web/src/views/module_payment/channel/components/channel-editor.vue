<template>
  <ElDrawer
    :model-value="modelValue"
    :title="channel ? `管理${channel.name}` : '管理支付渠道'"
    size="520px"
    @update:model-value="$emit('update:modelValue', $event)"
  >
    <template v-if="channel">
      <ElForm ref="formRef" :model="form" :rules="rules" label-position="top" class="editor-form">
        <div class="form-grid">
          <ElFormItem label="渠道名称" prop="name">
            <ElInput v-model="form.name" maxlength="64" />
          </ElFormItem>
          <ElFormItem label="运行环境" prop="mode">
            <ElSelect v-model="form.mode" class="w-full">
              <ElOption value="production" label="生产环境" />
              <ElOption value="sandbox" label="沙箱环境" />
            </ElSelect>
          </ElFormItem>
        </div>
        <div class="form-grid">
          <ElFormItem label="签约费率（%）" prop="fee_rate">
            <ElInputNumber
              v-model="form.fee_rate"
              :min="0"
              :max="100"
              :precision="4"
              :step="0.01"
              class="w-full!"
            />
          </ElFormItem>
          <ElFormItem label="结算周期" prop="settlement_cycle">
            <ElSelect v-model="form.settlement_cycle" class="w-full">
              <ElOption value="T+0" label="T+0" />
              <ElOption value="T+1" label="T+1" />
              <ElOption value="D+1" label="D+1" />
            </ElSelect>
          </ElFormItem>
        </div>
        <ElFormItem label="支付场景" prop="scenes">
          <ElCheckboxGroup v-model="form.scenes">
            <ElCheckbox value="PC收银台">PC 收银台</ElCheckbox>
            <ElCheckbox value="二维码支付">二维码支付</ElCheckbox>
            <ElCheckbox value="移动端支付">移动端支付</ElCheckbox>
          </ElCheckboxGroup>
        </ElFormItem>
        <ElFormItem label="运营备注" prop="description">
          <ElInput
            v-model="form.description"
            type="textarea"
            :rows="3"
            maxlength="255"
            show-word-limit
          />
        </ElFormItem>
      </ElForm>

      <section class="env-panel">
        <div class="env-panel-title">
          <div>
            <strong>服务端环境变量</strong>
            <span>{{
              channel.configured ? "已全部识别" : `待补充 ${channel.missing_fields.length} 项`
            }}</span>
          </div>
          <ElTag :type="channel.configured ? 'success' : 'warning'" effect="light">
            {{ channel.configured ? "就绪" : "未就绪" }}
          </ElTag>
        </div>
        <ul>
          <li
            v-for="field in channel.environment_fields"
            :key="field"
            :class="{ missing: channel.missing_fields.includes(field) }"
          >
            <FaSvgIcon
              :icon="
                channel.missing_fields.includes(field)
                  ? 'ri:close-circle-line'
                  : 'ri:checkbox-circle-line'
              "
            />
            <code>{{ field }}</code>
          </li>
        </ul>
      </section>
    </template>

    <template #footer>
      <ElButton @click="$emit('update:modelValue', false)">取消</ElButton>
      <ElButton type="primary" :loading="saving" @click="submit">保存设置</ElButton>
    </template>
  </ElDrawer>
</template>

<script setup lang="ts">
import type { FormInstance, FormRules } from "element-plus";
import type { PaymentChannel, PaymentChannelForm } from "@/api/module_payment/channel";

const props = defineProps<{
  modelValue: boolean;
  channel: PaymentChannel | null;
  saving: boolean;
}>();

const emit = defineEmits<{
  save: [form: PaymentChannelForm];
  "update:modelValue": [value: boolean];
}>();

const formRef = ref<FormInstance>();
const form = reactive<PaymentChannelForm>({
  name: "",
  mode: "production",
  fee_rate: 0,
  settlement_cycle: "T+1",
  scenes: [],
  description: "",
  order: 999,
});
const rules: FormRules<PaymentChannelForm> = {
  name: [{ required: true, message: "请输入渠道名称", trigger: "blur" }],
  mode: [{ required: true, message: "请选择运行环境", trigger: "change" }],
  settlement_cycle: [{ required: true, message: "请选择结算周期", trigger: "change" }],
  scenes: [
    { type: "array", required: true, min: 1, message: "至少选择一个支付场景", trigger: "change" },
  ],
};

watch(
  () => props.channel,
  (channel) => {
    if (!channel) return;
    Object.assign(form, {
      name: channel.name,
      mode: channel.mode,
      fee_rate: Number(channel.fee_rate),
      settlement_cycle: channel.settlement_cycle,
      scenes: [...channel.scenes],
      description: channel.description || "",
      order: channel.order,
    });
    nextTick(() => formRef.value?.clearValidate());
  },
  { immediate: true }
);

async function submit(): Promise<void> {
  await formRef.value?.validate();
  emit("save", { ...form, scenes: [...form.scenes] });
}
</script>

<style scoped>
.editor-form {
  margin-top: 0;
}

.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
}

.env-panel {
  padding: 17px;
  margin-top: 8px;
  background: var(--el-fill-color-extra-light);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 12px;
}

.env-panel-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.env-panel-title strong,
.env-panel-title span {
  display: block;
}

.env-panel-title strong {
  font-size: 13px;
  color: var(--el-text-color-primary);
}

.env-panel-title span {
  margin-top: 3px;
  font-size: 11px;
  color: var(--el-text-color-secondary);
}

.env-panel ul {
  display: grid;
  gap: 9px;
  padding: 0;
  margin: 15px 0 0;
  list-style: none;
}

.env-panel li {
  display: flex;
  gap: 8px;
  align-items: center;
  font-size: 12px;
  color: var(--el-color-success);
}

.env-panel li.missing {
  color: var(--el-color-warning);
}

.env-panel code {
  color: var(--el-text-color-regular);
}

@media (width <= 620px) {
  .form-grid {
    grid-template-columns: 1fr;
    gap: 0;
  }
}
</style>
