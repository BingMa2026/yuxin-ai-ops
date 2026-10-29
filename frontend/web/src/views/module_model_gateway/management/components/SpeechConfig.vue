<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
import { onBeforeRouteLeave } from "vue-router";
import { ElMessageBox } from "element-plus";
import API, { type SpeechConfig, type SpeechModel } from "@/api/module_speech";
import { useClientAppStore } from "@stores";

const props = defineProps<{ appId: number; appName: string }>();
const store = useClientAppStore();
const form = reactive<SpeechConfig>({
  catalog_model_id: null,
  status: "inactive",
  max_duration_seconds: 60,
  daily_limit_seconds: 600,
  revision: 0,
});
const models = ref<SpeechModel[]>([]),
  loading = ref(true),
  failed = ref(false),
  saving = ref(false),
  snapshot = ref("");
let alive = true;
const source = `speech-config-${props.appId}`;
const dirty = computed(() => Boolean(snapshot.value) && JSON.stringify(form) !== snapshot.value);
const scope = () => alive && store.currentApp?.id === props.appId;
async function load() {
  loading.value = true;
  failed.value = false;
  try {
    const [config, options] = await Promise.all([API.config(), API.models()]);
    if (!scope()) return;
    Object.assign(form, config.data.data);
    models.value = options.data.data;
    snapshot.value = JSON.stringify(form);
  } catch {
    if (scope()) failed.value = true;
  } finally {
    if (scope()) loading.value = false;
  }
}
async function save() {
  if (saving.value || !scope()) return;
  const confirmed = await ElMessageBox.confirm(
    `将更新「${props.appName}」的语音输入配置，保存后立即生效。`,
    "保存语音配置",
    { confirmButtonText: "保存并生效", cancelButtonText: "取消" }
  )
    .then(() => true)
    .catch(() => false);
  if (!confirmed || !scope()) return;
  saving.value = true;
  try {
    const result = await API.save({ ...form });
    if (!scope()) return;
    Object.assign(form, result.data.data);
    snapshot.value = JSON.stringify(form);
  } catch {
    /* Request layer reports errors. */
  } finally {
    if (scope()) saving.value = false;
  }
}
watch(dirty, (value) => store.markDirty(source, value));
onBeforeRouteLeave(
  async () =>
    !dirty.value ||
    (await ElMessageBox.confirm("语音配置尚未保存，是否放弃修改？", "离开配置", {
      confirmButtonText: "放弃修改",
      cancelButtonText: "继续编辑",
    })
      .then(() => true)
      .catch(() => false))
);
const onUnload = (event: BeforeUnloadEvent) => {
  if (dirty.value) {
    event.preventDefault();
    event.returnValue = "";
  }
};
onMounted(() => {
  void load();
  window.addEventListener("beforeunload", onUnload);
});
onBeforeUnmount(() => {
  window.removeEventListener("beforeunload", onUnload);
  alive = false;
  store.markDirty(source, false);
});
</script>
<template>
  <section class="speech-config" v-loading="loading">
    <ElAlert v-if="failed" title="语音配置加载失败" type="error" :closable="false">
      <ElButton @click="load">重新加载</ElButton>
    </ElAlert>
    <ElForm v-else-if="!loading" label-position="top" :disabled="saving" class="speech-form">
      <div class="speech-status">
        <div>
          <strong>聊天框语音输入</strong>
          <p>录音转为文字，填入草稿后由用户发送。</p>
        </div>
        <ElSwitch
          v-model="form.status"
          active-value="active"
          inactive-value="inactive"
          :active-text="form.status === 'active' ? '已开启' : '已关闭'"
          aria-label="语音输入开关"
        />
      </div>
      <div class="speech-fields">
        <ElFormItem label="语音识别模型" class="speech-model">
          <ElSelect
            v-model="form.catalog_model_id"
            clearable
            filterable
            placeholder="选择已启用的语音识别模型"
            @clear="form.catalog_model_id = null"
          >
            <ElOption
              v-for="model in models"
              :key="model.id"
              :value="model.id"
              :label="`${model.name} · ${model.provider_name}${model.status === 'active' ? '' : '（未启用）'}`"
              :disabled="model.status !== 'active'"
            />
          </ElSelect>
        </ElFormItem>
        <ElFormItem label="单次录音上限">
          <div class="speech-number">
            <ElInputNumber
              v-model="form.max_duration_seconds"
              :min="5"
              :max="60"
              controls-position="right"
            /><span>秒</span>
          </div>
        </ElFormItem>
        <ElFormItem label="每人每日上限">
          <div class="speech-number">
            <ElInputNumber
              v-model="form.daily_limit_seconds"
              :min="60"
              :max="3600"
              controls-position="right"
            /><span>秒</span>
          </div>
        </ElFormItem>
      </div>
      <div class="speech-footer">
        <p>用户不选择语音模型，不扣积分。语音采购成本按录音时长估算，已计入经营报表。</p>
        <ElButton
          v-hasPerm="['workspace:resource:model:edit']"
          type="primary"
          :loading="saving"
          :disabled="!dirty || (form.status === 'active' && !form.catalog_model_id)"
          @click="save"
          >保存配置</ElButton
        >
      </div>
    </ElForm>
  </section>
</template>
<style scoped>
.speech-config {
  min-height: 180px;
}
.speech-status {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 20px;
  padding: 4px 0 20px;
}
.speech-status strong {
  font-size: 14px;
  font-weight: 500;
  color: var(--el-text-color-primary);
}
.speech-status p,
.speech-footer p {
  margin: 6px 0 0;
  color: var(--el-text-color-secondary);
  font-size: 13px;
  line-height: 1.6;
}
.speech-fields {
  display: grid;
  grid-template-columns: minmax(240px, 2fr) repeat(2, minmax(160px, 1fr));
  gap: 24px;
  max-width: 1100px;
}
.speech-fields :deep(.el-form-item) {
  min-width: 0;
  margin-bottom: 20px;
}
.speech-number {
  display: flex;
  gap: 10px;
  align-items: center;
  color: var(--el-text-color-secondary);
}
.speech-number :deep(.el-input-number) {
  width: 140px;
}
.speech-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  border-top: 1px solid var(--el-border-color-lighter);
  padding-top: 16px;
}
.speech-footer p {
  margin: 0;
}
@media (max-width: 900px) {
  .speech-fields {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 0 16px;
  }
  .speech-model {
    grid-column: 1 / -1;
  }
}
@media (max-width: 540px) {
  .speech-fields {
    grid-template-columns: minmax(0, 1fr);
  }
  .speech-footer {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
