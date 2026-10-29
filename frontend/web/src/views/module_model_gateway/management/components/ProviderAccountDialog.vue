<template>
  <ElDialog
    v-model="visible"
    :title="account ? '编辑供应商账号' : '新增供应商账号'"
    width="min(620px, 94vw)"
    destroy-on-close
  >
    <ElForm label-position="top">
      <ElFormItem label="供应商"
        ><ElSelect
          v-model="form.template_id"
          filterable
          :disabled="!!account"
          @change="selectTemplate"
          ><ElOption
            v-for="item in templates"
            :key="item.id"
            :label="item.name"
            :value="item.id || 0" /></ElSelect
      ></ElFormItem>
      <div class="grid">
        <ElFormItem label="账号名称"
          ><ElInput v-model="form.name" placeholder="例如 OpenAI 主账号" /></ElFormItem
        ><ElFormItem label="内部编码"
          ><ElInput v-model="form.code" placeholder="openai_primary" :disabled="!!account"
        /></ElFormItem>
      </div>
      <ElFormItem label="API 地址"
        ><ElInput v-model="form.endpoint" placeholder="https://.../v1"
      /></ElFormItem>
      <ElFormItem :label="`响应等待上限（秒，最多 ${maxAccountTimeout}）`"
        ><ElInputNumber
          v-model="form.timeout_seconds"
          :min="1"
          :max="maxAccountTimeout"
          :precision="0"
      /></ElFormItem>
      <div class="credentials">
        <ElFormItem
          v-for="field in selected?.field_schema || []"
          :key="field.key"
          :label="field.label"
          :required="field.required && !account"
          ><ElInput
            v-model="form.settings[field.key]"
            :type="
              field.type === 'password'
                ? 'password'
                : field.type === 'textarea'
                  ? 'textarea'
                  : 'text'
            "
            :show-password="field.type === 'password'"
            :placeholder="
              account && form.settings[field.key] === ''
                ? account.masked_summary[field.key] || '留空则不修改'
                : ''
            "
        /></ElFormItem>
      </div>
      <p class="credential-help">
        {{
          account
            ? "密钥留空表示保留原值。修改后保存，再到详情页测试并发现模型。"
            : "填写供应商平台创建的 API Key；测试成功后保存，再到详情页测试并发现模型。"
        }}
      </p>
    </ElForm>
    <template #footer
      ><ElButton @click="visible = false">取消</ElButton
      ><ElButton v-if="!account" :disabled="saving" :loading="testing" @click="testConnection"
        >测试连接</ElButton
      ><ElButton type="primary" :disabled="testing" :loading="saving" @click="submit"
        >保存账号</ElButton
      ></template
    >
  </ElDialog>
</template>

<script setup lang="ts">
import { ElMessage } from "element-plus";
import ModelGatewayAPI from "@/api/module_model_gateway";
import type { ProviderAccount, ProviderTemplate } from "@/api/module_model_gateway";
const props = defineProps<{
  modelValue: boolean;
  templates: ProviderTemplate[];
  account?: ProviderAccount;
  saving: boolean;
}>();
const emit = defineEmits<{ "update:modelValue": [boolean]; save: [Record<string, unknown>] }>();
const visible = computed({
  get: () => props.modelValue,
  set: (value) => emit("update:modelValue", value),
});
const selected = computed(() => props.templates.find((item) => item.id === form.template_id));
// 旧版后端尚未返回上限时，按其实际支持的 600 秒处理。
const maxAccountTimeout = computed(() => {
  const value = selected.value?.max_timeout_seconds;
  return typeof value === "number" && Number.isInteger(value) && value > 0 ? value : 600;
});
const form = reactive({
  template_id: 0,
  code: "",
  name: "",
  endpoint: "",
  settings: {} as Record<string, string>,
  timeout_seconds: 120,
  retry_count: 1,
  status: "inactive",
});
const testing = ref(false);
function selectTemplate() {
  const item = selected.value;
  if (!props.account) {
    form.endpoint = item?.default_endpoint || "";
    form.name = `${item?.name || "供应商"} 主账号`;
    form.code = `${item?.code || "provider"}_primary`;
  }
  form.settings = {};
  for (const field of item?.field_schema || []) form.settings[field.key] = "";
}
function validate() {
  if (
    !form.template_id ||
    !form.code ||
    !form.name ||
    (!form.endpoint && selected.value?.protocol !== "bedrock")
  ) {
    ElMessage.warning("请完整填写供应商账号");
    return false;
  }
  if (
    !Number.isInteger(form.timeout_seconds) ||
    form.timeout_seconds < 1 ||
    form.timeout_seconds > maxAccountTimeout.value
  ) {
    ElMessage.warning(`响应等待上限须为 1～${maxAccountTimeout.value} 秒`);
    return false;
  }
  for (const field of selected.value?.field_schema || []) {
    if (field.required && !form.settings[field.key] && !props.account?.masked_summary[field.key]) {
      ElMessage.warning(`请填写${field.label}`);
      return false;
    }
  }
  return true;
}
function submit() {
  if (!validate()) return;
  emit("save", { ...form, settings: { ...form.settings } });
}
async function testConnection() {
  if (props.account) return ElMessage.info("已保存账号请在详情页使用“测试并发现模型”");
  if (!validate()) return;
  testing.value = true;
  try {
    const response = await ModelGatewayAPI.testConnection({
      template_id: form.template_id,
      endpoint: form.endpoint,
      settings: { ...form.settings },
      timeout_seconds: Math.min(form.timeout_seconds, 60),
    });
    ElMessage.success(`连接成功，发现 ${response.data.data?.length || 0} 个模型`);
  } catch {
    // 请求层已展示供应商返回的具体错误；此处消化事件异常，避免触发组件错误边界。
  } finally {
    testing.value = false;
  }
}
watch(
  () => props.modelValue,
  (value) => {
    if (value) {
      const account = props.account;
      Object.assign(form, {
        template_id: account?.template_id || props.templates[0]?.id || 0,
        code: account?.code || "",
        name: account?.name || "",
        endpoint: account?.endpoint || props.templates[0]?.default_endpoint || "",
        settings: {},
        timeout_seconds: account?.timeout_seconds || 120,
        retry_count: account?.retry_count ?? 1,
        status: account?.status || "inactive",
      });
      selectTemplate();
      if (account) form.endpoint = account.endpoint;
    }
  }
);
</script>

<style scoped>
.grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0 14px;
}

.el-select {
  width: 100%;
}
@media (width<=620px) {
  .grid {
    grid-template-columns: 1fr;
  }
}

.credentials .el-input {
  width: 100%;
}

.credential-help {
  margin: 0 0 8px;
  font-size: 12px;
  line-height: 1.7;
  color: var(--el-text-color-secondary);
}
</style>
