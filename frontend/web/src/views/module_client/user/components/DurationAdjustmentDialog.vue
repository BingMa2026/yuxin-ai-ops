<template>
  <ElDialog
    v-model="visible"
    title="调整使用天数"
    width="min(680px, 94vw)"
    :close-on-click-modal="false"
    :close-on-press-escape="!saving"
    :show-close="!saving"
  >
    <div v-loading="loading" class="duration-body">
      <p>用户：{{ user?.display_name || user?.username }}（{{ user?.username }}）</p>
      <ElAlert v-if="failed" title="权益信息暂时无法获取，请重试" type="error" :closable="false" />
      <template v-if="state">
        <div class="duration-summary">
          <span
            >当前到期时间：<strong>{{ dateText(state.expires_at) }}</strong></span
          >
          <span
            >剩余 {{ Math.ceil(state.remaining_seconds / 86400) }} 天（不足一天按一天显示）</span
          >
        </div>
        <ElAlert
          :title="
            state.status === 'cancelled'
              ? '订阅已停用：调整天数后仍保持停用。'
              : '增加天数不需要支付；有效期内累加，过期后从操作时起算。'
          "
          :type="state.status === 'cancelled' ? 'warning' : 'info'"
          :closable="false"
        />
        <ElForm label-position="top" :disabled="saving || loading" class="duration-form">
          <ElFormItem label="调整方式">
            <ElRadioGroup v-model="form.direction">
              <ElRadioButton value="grant">增加天数</ElRadioButton>
              <ElRadioButton value="deduct" :disabled="state.remaining_seconds <= 0"
                >扣减天数</ElRadioButton
              >
            </ElRadioGroup>
          </ElFormItem>
          <ElFormItem v-if="form.direction === 'grant'" label="关联时长套餐">
            <ElSelect v-model="form.catalog_plan_id" placeholder="选择当前客户端的时长套餐">
              <ElOption
                v-for="plan in state.plans"
                :key="plan.id"
                :label="plan.name"
                :value="plan.id"
              />
            </ElSelect>
            <span v-if="!state.plans.length" class="form-hint"
              >请先在预算中心的产品刊例中创建时长套餐。</span
            >
          </ElFormItem>
          <ElFormItem label="调整天数（1～3650 天）">
            <ElInputNumber v-model="form.days" :min="1" :max="3650" :precision="0" />
          </ElFormItem>
          <ElFormItem label="调整原因">
            <ElInput
              v-model="form.reason"
              type="textarea"
              :rows="2"
              :maxlength="500"
              show-word-limit
              placeholder="请填写开通、补偿或扣减原因（至少 2 个字）"
            />
          </ElFormItem>
          <p class="form-hint">
            预计到期时间：{{ dateText(previewEnd) }}，以服务端实际处理时间为准。
          </p>
          <p v-if="form.direction === 'deduct'" class="form-hint">
            只扣减未使用的时长；扣减超过剩余时长时，订阅立即到期。
          </p>
        </ElForm>
        <details class="duration-history">
          <summary>最近调整记录（{{ state.records.length }} 条，最多显示 20 条）</summary>
          <p v-if="!state.records.length" class="form-hint">暂无人工调整记录</p>
          <article v-for="record in state.records" :key="record.id">
            <strong
              >{{ record.direction === "grant" ? "增加" : "扣减" }} {{ record.days }} 天</strong
            >
            <span>{{ record.operator_name }} · {{ dateText(record.created_time) }}</span>
            <span
              >{{ dateText(record.before_expires_at) }} →
              {{ dateText(record.after_expires_at) }}</span
            >
            <span v-if="record.direction === 'deduct'"
              >实际扣减约 {{ (Math.abs(record.seconds_delta) / 86400).toFixed(2) }} 天</span
            >
            <p>{{ record.reason }}</p>
          </article>
        </details>
      </template>
    </div>
    <template #footer>
      <ElButton :disabled="saving || loading" @click="load">刷新权益</ElButton>
      <ElButton :disabled="saving" @click="visible = false">关闭</ElButton>
      <ElButton type="primary" :loading="saving" :disabled="!canSubmit || loading" @click="save"
        >确认调整</ElButton
      >
    </template>
  </ElDialog>
</template>

<script setup lang="ts">
import { ElMessageBox } from "element-plus";
import DurationAPI, { type DurationState } from "@/api/module_billing/duration";
import type { ClientUserInfo } from "@/api/module_client/user";
import { useClientAppStore } from "@stores";

const visible = defineModel<boolean>({ required: true });
const props = defineProps<{ user?: ClientUserInfo }>();
const emit = defineEmits<{ saved: [] }>();
const appStore = useClientAppStore();
const state = ref<DurationState>();
const loading = ref(false);
const saving = ref(false);
const failed = ref(false);
const form = reactive({
  direction: "grant" as "grant" | "deduct",
  days: 30,
  catalog_plan_id: undefined as number | undefined,
  reason: "",
});
let generation = 0;
let submission: { fingerprint: string; key: string } | undefined;
const canSubmit = computed(
  () =>
    !!state.value &&
    Number.isInteger(form.days) &&
    form.days >= 1 &&
    form.days <= 3650 &&
    form.reason.trim().length >= 2 &&
    (form.direction === "grant" ? !!form.catalog_plan_id : state.value.remaining_seconds > 0)
);
const previewEnd = computed(() => {
  if (!state.value || !Number.isFinite(form.days)) return null;
  const now = new Date(state.value.server_time).getTime();
  const end = state.value.expires_at ? new Date(state.value.expires_at).getTime() : now;
  return new Date(
    form.direction === "grant"
      ? Math.max(end, now) + form.days * 86400000
      : Math.max(now, end - form.days * 86400000)
  ).toISOString();
});
function dateText(value: string | null) {
  if (!value) return "未开通";
  // Audit dates from older database adapters may omit the UTC suffix.
  const normalized = /(?:Z|[+-]\d{2}:\d{2})$/i.test(value) ? value : `${value}Z`;
  const date = new Date(normalized);
  return Number.isFinite(date.getTime())
    ? date.toLocaleString("zh-CN", { hour12: false })
    : "时间暂不可用";
}
async function load() {
  const userId = props.user?.id;
  if (!visible.value || !userId || saving.value) return;
  const current = ++generation;
  loading.value = true;
  failed.value = false;
  state.value = undefined;
  try {
    const response = await DurationAPI.state(userId);
    if (current !== generation) return;
    const data = response.data.data;
    if (!data) throw new Error("missing duration state");
    state.value = data;
    form.catalog_plan_id =
      data.plans.find((plan) => plan.id === data.catalog_plan_id)?.id || data.plans[0]?.id;
    submission = undefined;
  } catch {
    if (current === generation) failed.value = true;
  } finally {
    if (current === generation) loading.value = false;
  }
}
async function save() {
  if (!canSubmit.value || !state.value || !props.user?.id || saving.value) return;
  saving.value = true;
  const userId = props.user.id;
  const current = generation;
  const body = {
    direction: form.direction,
    days: form.days,
    catalog_plan_id: form.direction === "grant" ? form.catalog_plan_id : undefined,
    reason: form.reason.trim(),
    expected_expires_at: state.value.expires_at,
  };
  try {
    if (body.direction === "deduct") {
      await ElMessageBox.confirm(
        `将为 ${props.user.display_name || props.user.username} 扣减 ${body.days} 天。预计到期时间：${dateText(previewEnd.value)}。超过剩余时长将立即到期。`,
        "确认扣减使用天数",
        { type: "warning", confirmButtonText: "确认扣减", cancelButtonText: "取消" }
      );
    }
    if (current !== generation || !visible.value) return;
    const fingerprint = JSON.stringify(body);
    if (submission?.fingerprint !== fingerprint)
      submission = { fingerprint, key: crypto.randomUUID() };
    await DurationAPI.adjust(userId, { ...body, idempotency_key: submission.key });
    if (current !== generation) return;
    visible.value = false;
    emit("saved");
  } catch {
    // The request interceptor reports API failures. Retain the request key for
    // safe retries after an uncertain network outcome; refresh handles conflicts.
  } finally {
    saving.value = false;
  }
}
watch(
  [visible, () => props.user?.id],
  () => {
    ++generation;
    state.value = undefined;
    loading.value = false;
    submission = undefined;
    Object.assign(form, { direction: "grant", days: 30, reason: "", catalog_plan_id: undefined });
    if (visible.value) void load();
  },
  { immediate: true }
);
watch(
  () => appStore.currentApp?.id,
  () => {
    ++generation;
    visible.value = false;
  }
);
watch(visible, (value) => appStore.markDirty("duration-adjustment", value), { immediate: true });
onUnmounted(() => {
  ++generation;
  appStore.markDirty("duration-adjustment", false);
});
</script>

<style scoped>
.duration-body {
  min-height: 100px;
  max-height: 65vh;
  overflow-y: auto;
  overflow-wrap: anywhere;
}

.duration-summary {
  display: grid;
  gap: 6px;
  margin-bottom: 16px;
}

.duration-form {
  margin-top: 16px;
}

.form-hint {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.duration-history {
  padding-top: 12px;
  border-top: 1px solid var(--el-border-color-light);
}

.duration-history summary {
  cursor: pointer;
}

.duration-history article {
  display: grid;
  gap: 5px;
  padding: 12px 0;
  border-bottom: 1px solid var(--el-border-color-light);
}

.duration-history article span {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.duration-history article p {
  margin: 0;
  white-space: pre-wrap;
}
</style>
