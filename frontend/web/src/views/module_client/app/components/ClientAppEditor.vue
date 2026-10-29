<template>
  <ElDialog
    v-model="visible"
    :title="app ? '编辑客户端' : '新增客户端'"
    width="min(560px, 94vw)"
    destroy-on-close
  >
    <ElForm ref="formRef" :model="form" :rules="rules" label-position="top">
      <div class="logo-editor">
        <span class="logo-preview"
          ><img v-if="form.logo" :src="form.logo" /><b v-else>{{
            form.name?.slice(0, 1) || "客"
          }}</b></span
        >
        <div>
          <strong>产品图标</strong><small>建议上传 512×512 的 PNG、JPG 或 WebP 图片。</small>
          <ElUpload
            :show-file-list="false"
            accept="image/png,image/jpeg,image/webp"
            :http-request="uploadLogo"
            ><ElButton :loading="logoUploading">上传图标</ElButton></ElUpload
          >
        </div>
      </div>
      <div class="editor-grid">
        <ElFormItem label="应用名称" prop="name"
          ><ElInput v-model="form.name" maxlength="64"
        /></ElFormItem>
        <ElFormItem label="应用编码" prop="code">
          <ElInput v-model="form.code" :disabled="Boolean(app)" placeholder="如 bid_agent" />
          <small>发布后不可修改，用于安装包识别应用。</small>
        </ElFormItem>
        <ElFormItem label="当前版本"
          ><ElInput :model-value="form.client_version || '由版本中心发布后自动更新'" disabled
        /></ElFormItem>
        <ElFormItem label="排序">
          <ElInputNumber v-model="form.order" :min="1" :max="999" controls-position="right" />
        </ElFormItem>
        <ElFormItem label="状态">
          <ElSelect v-model="form.status"
            ><ElOption label="草稿" value="draft" /><ElOption
              label="运营中"
              value="active" /><ElOption label="已停用" value="inactive"
          /></ElSelect>
        </ElFormItem>
      </div>
      <ElFormItem label="服务模式">
        <ElRadioGroup v-model="form.service_mode" class="model-mode-control" aria-label="服务模式">
          <ElRadio value="credits_only">含 token 费用</ElRadio>
          <ElRadio value="duration_only">token 自费</ElRadio>
          <ElRadio value="user_choice">均支持</ElRadio>
        </ElRadioGroup>
        <small>均支持时由用户选择订阅类型，同一时间仅一种模式生效。</small>
      </ElFormItem>
      <ElFormItem label="简介"
        ><ElInput
          v-model="form.description"
          type="textarea"
          :rows="3"
          maxlength="1000"
          show-word-limit
      /></ElFormItem>
      <ElFormItem
        ><ElCheckbox v-model="form.registration_enabled"
          >允许客户端用户自助注册</ElCheckbox
        ></ElFormItem
      >
    </ElForm>
    <template #footer>
      <ElButton @click="visible = false">取消</ElButton>
      <ElButton type="primary" :loading="saving" @click="submit">保存</ElButton>
    </template>
  </ElDialog>
</template>

<script setup lang="ts">
import type { FormInstance, FormRules } from "element-plus";
import type { UploadRequestOptions } from "element-plus";
import type { ClientAppForm, ClientAppInfo } from "@/api/module_client/app";
import FileAPI from "@/api/module_storage/file";

const props = defineProps<{ modelValue: boolean; app?: ClientAppInfo; saving?: boolean }>();
const emit = defineEmits<{ "update:modelValue": [boolean]; save: [ClientAppForm] }>();
const visible = computed({
  get: () => props.modelValue,
  set: (value) => emit("update:modelValue", value),
});
const formRef = ref<FormInstance>();
const logoUploading = ref(false);
const form = reactive<ClientAppForm>({
  name: "",
  code: "",
  status: "draft",
  service_mode: "user_choice",
  registration_enabled: false,
  order: 999,
});
const rules: FormRules = {
  name: [{ required: true, message: "请输入应用名称", trigger: "blur" }],
  code: [
    {
      required: true,
      pattern: /^[a-z][a-z0-9_]{1,63}$/,
      message: "请输入合法的小写应用编码",
      trigger: "blur",
    },
  ],
};

watch(
  () => props.app,
  (app) =>
    Object.assign(
      form,
      app
        ? {
            ...app,
            service_mode:
              app.service_mode ??
              (app.platform_model_enabled === false ? "duration_only" : "credits_only"),
          }
        : {
            name: "",
            code: "",
            status: "draft",
            service_mode: "user_choice",
            registration_enabled: false,
            order: 999,
            description: "",
            client_version: "",
          }
    ),
  { immediate: true }
);

async function submit() {
  await formRef.value?.validate();
  const { platform_model_enabled: _legacy, ...values } = form;
  emit("save", { ...values, expected_policy_version: props.app?.model_policy_version });
}
async function uploadLogo(options: UploadRequestOptions) {
  if (options.file.size > 5 * 1024 * 1024) throw new Error("图片不能超过 5MB");
  logoUploading.value = true;
  try {
    const data = new FormData();
    data.append("file", options.file);
    data.append("remote_path", "client-apps/logos/");
    const response = await FileAPI.uploadFile(data);
    const payload = response.data.data as { file_url?: string } | undefined;
    if (!payload?.file_url) throw new Error("未取得图片地址");
    form.logo = payload.file_url;
    options.onSuccess?.(payload);
  } catch (error) {
    options.onError?.(error as never);
    throw error;
  } finally {
    logoUploading.value = false;
  }
}
</script>

<style scoped>
.model-mode-control {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
  align-items: center;
  width: 100%;
}

.model-mode-control > small {
  flex: 1;
  min-width: 0;
  margin-top: 0;
  line-height: 1.5;
}

.editor-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0 18px;
}
.logo-editor {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 18px;
  padding: 14px;
  border-radius: 10px;
  background: var(--el-fill-color-lighter);
}
.logo-editor > div {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 6px;
}
.logo-preview {
  display: grid;
  place-items: center;
  width: 64px;
  height: 64px;
  flex-shrink: 0;
  color: var(--el-color-primary);
  font-size: 22px;
}
.logo-preview img {
  width: 100%;
  height: 100%;
  object-fit: contain;
}
small {
  display: block;
  margin-top: 5px;
  color: var(--el-text-color-secondary);
}
@media (width <= 620px) {
  .editor-grid {
    grid-template-columns: 1fr;
  }
}
</style>
