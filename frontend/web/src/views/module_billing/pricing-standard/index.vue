<template>
  <main class="ops-page fa-full-height">
    <section class="layout">
      <aside class="version-list" v-loading="loading">
        <div class="version-list-heading">
          全平台价格版本 <span>{{ versions.length }}</span>
        </div>
        <button
          v-for="item in versions"
          :key="item.id"
          :class="{ active: selected?.id === item.id }"
          :aria-pressed="selected?.id === item.id"
          @click="selectVersion(item)"
        >
          <span class="version-title"
            ><strong>{{ item.name }}</strong
            ><small>{{ item.version }}</small></span
          >
          <span class="version-status" :class="item.status">{{ statusName(item.status) }}</span>
          <em>{{ item.template_count }} 个套餐模板</em>
        </button>
        <ElAlert v-if="failed" title="版本加载失败" type="error" :closable="false" />
        <ElButton v-if="failed" link type="primary" @click="load()">重新加载</ElButton>
        <ElEmpty
          v-if="!versions.length && !loading && !failed"
          description="暂无价格版本"
          :image-size="72"
        />
      </aside>
      <section class="content-card">
        <template v-if="selected">
          <header class="content-head">
            <div>
              <div class="preview-eyebrow">
                {{ selected.version }} · {{ selected.status === "draft" ? "草稿预览" : "套餐预览" }}
              </div>
              <h2>{{ selected.name }}</h2>
            </div>
            <div class="content-actions">
              <ElButton text :loading="loading || preview?.loading" @click="refresh">刷新</ElButton>
              <ElButton
                v-hasPerm="['workspace:budget:price:create']"
                text
                :disabled="loading || templateLoading || templateFailed || mutating"
                @click="openCreate"
                >复制为新版本</ElButton
              >
              <ElButton
                v-hasPerm="['workspace:budget:price:create']"
                :disabled="loading || templateLoading || templateFailed || mutating"
                @click="openEdit"
                >编辑版本</ElButton
              >
              <ElButton
                v-if="selected.status !== 'published'"
                v-hasPerm="['workspace:budget:price:create']"
                text
                type="danger"
                :disabled="loading || mutating"
                @click="removeVersion"
                >删除版本</ElButton
              >
              <ElButton
                v-if="selected.status !== 'published'"
                v-hasPerm="['workspace:budget:price:publish']"
                :disabled="loading || templateLoading || templateFailed"
                :loading="mutating"
                type="primary"
                @click="publish"
                >发布版本</ElButton
              >
            </div>
          </header>
          <ElAlert
            v-if="selected.status === 'draft' && templateFailed"
            title="草稿加载失败，请刷新重试"
            type="error"
            :closable="false"
          />
          <PricingLivePreview
            ref="preview"
            :version="selected"
            :templates="templates"
            :template-loading="templateLoading"
          />
        </template>
        <div v-else>
          <ElEmpty description="暂无价格版本" /><ElButton
            v-hasPerm="['workspace:budget:price:create']"
            type="primary"
            @click="openCreate"
            >新建价格体系</ElButton
          >
        </div>
      </section>
    </section>
    <PricingEditorDrawer
      ref="editor"
      :visible="dialogVisible"
      :form="form"
      @update:form="Object.assign(form, $event)"
      :editing="!!editingId"
      :saving="saving"
      :status="selected?.status"
      :source-name="selected?.name"
      @close="dialogVisible = false"
      @save="save"
      @add="addTemplate"
    />
  </main>
</template>

<script setup lang="ts">
import { ElMessage, ElMessageBox } from "element-plus";
import BillingAPI, {
  type PricingTemplate,
  type PricingVersion,
  type PricingVersionForm,
} from "@/api/module_billing";
import { useClientAppStore } from "@stores";
import PricingLivePreview from "./PricingLivePreview.vue";
import PricingEditorDrawer from "./PricingEditorDrawer.vue";
const editor = ref<InstanceType<typeof PricingEditorDrawer>>();
const mutating = ref(false);
defineOptions({ name: "BudgetPriceSystem" });
const clientAppStore = useClientAppStore();
const preview = ref<InstanceType<typeof PricingLivePreview>>();
const failed = ref(false);
const templateLoading = ref(false);
const templateFailed = ref(false);
let templateRequestId = 0;
const versions = ref<PricingVersion[]>([]);
const templates = ref<PricingTemplate[]>([]);
const selected = ref<PricingVersion>();
const loading = ref(false);
const saving = ref(false);
const dialogVisible = ref(false);
const editingId = ref<number>();
const blankTemplate = () => ({
  code: "",
  name: "",
  plan_type: "subscription" as const,
  tier_code: "starter" as const,
  tier_order: 10,
  billing_period_days: 30,
  one_time_price_fen: 0,
  recurring_price_fen: 0,
  total_credits: 1000,
  release_plan: [{ offset_day: 0, amount: 1000, account_type: "current_cycle" as const }],
  credit_valid_days: 30,
  renewal_rule: "按订阅周期续费",
  benefits: [] as string[],
  requires_active_subscription: false,
  order: 999,
});
const form = reactive<PricingVersionForm>({
  version: "",
  name: "",
  margin_baseline: 60,
  credits_per_yuan: 1000,
  subscription_cycle_days: 30,
  renewal_discount_rate: 0.9,
  margin_floor: 25,
  account_priority: [
    "activity_reward",
    "current_cycle",
    "monthly_reserve",
    "traffic_pack",
    "enterprise_pool",
    "manual",
  ],
  description: "",
  templates: [blankTemplate()],
});
const accountOptions = [
  { label: "活动赠送", value: "activity_reward" },
  { label: "当期权益", value: "current_cycle" },
  { label: "月度储备", value: "monthly_reserve" },
  { label: "流量积分包", value: "traffic_pack" },
  { label: "企业共享", value: "enterprise_pool" },
  { label: "人工调整", value: "manual" },
];
const statusName = (status: string) =>
  ({ draft: "草稿", published: "已发布", archived: "已归档" })[status] || status;
async function load(preferredId?: number) {
  loading.value = true;
  failed.value = false;
  try {
    const response = await BillingAPI.versions();
    versions.value = response.data.data || [];
    const firstVersion =
      versions.value.find((item) => item.id === (preferredId ?? selected.value?.id)) ||
      versions.value.find((item) => item.status === "published") ||
      versions.value.find((item) => item.status === "draft") ||
      versions.value[0];
    if (firstVersion) await selectVersion(firstVersion);
    else {
      ++templateRequestId;
      selected.value = undefined;
      templates.value = [];
      templateLoading.value = false;
    }
  } catch {
    failed.value = true;
  } finally {
    loading.value = false;
  }
}
async function selectVersion(item: PricingVersion) {
  const id = ++templateRequestId;
  selected.value = item;
  templates.value = [];
  templateLoading.value = true;
  templateFailed.value = false;
  try {
    const response = await BillingAPI.templates(item.id!);
    if (id === templateRequestId) templates.value = response.data.data || [];
  } catch {
    if (id === templateRequestId) templateFailed.value = true;
  } finally {
    if (id === templateRequestId) templateLoading.value = false;
  }
}
async function refresh() {
  await load(selected.value?.id);
  await preview.value?.load();
}
function cloneTemplate(item: PricingTemplate) {
  return {
    entitlement_kind: item.entitlement_kind ?? "credits",
    code: item.code,
    name: item.name,
    plan_type: item.plan_type,
    tier_code: item.tier_code,
    tier_order: item.tier_order,
    billing_period_days: item.billing_period_days,
    one_time_price_fen: item.one_time_price_fen,
    recurring_price_fen: item.recurring_price_fen,
    total_credits: item.total_credits,
    release_plan: item.release_plan.map((release) => ({ ...release })),
    credit_valid_days: item.credit_valid_days,
    renewal_rule: item.renewal_rule,
    benefits: [...item.benefits],
    requires_active_subscription: item.requires_active_subscription,
    order: item.order,
  };
}
function openCreate() {
  editingId.value = undefined;
  Object.assign(form, {
    version: "",
    name: "",
    effective_at: undefined,
    margin_baseline: selected.value?.margin_baseline ?? 60,
    credits_per_yuan: selected.value?.credits_per_yuan || 1000,
    subscription_cycle_days: selected.value?.subscription_cycle_days || 30,
    renewal_discount_rate: selected.value?.renewal_discount_rate || 0.9,
    margin_floor: selected.value?.margin_floor ?? 25,
    account_priority: selected.value?.account_priority?.length
      ? [...selected.value.account_priority]
      : accountOptions.map((item) => item.value),
    description: "",
    templates: templates.value.length ? templates.value.map(cloneTemplate) : [blankTemplate()],
  });
  dialogVisible.value = true;
}
function openEdit() {
  if (!selected.value?.id) return;
  editingId.value = selected.value.id;
  Object.assign(form, {
    version: selected.value.version,
    name: selected.value.name,
    margin_baseline: selected.value.margin_baseline,
    credits_per_yuan: selected.value.credits_per_yuan,
    subscription_cycle_days: selected.value.subscription_cycle_days,
    renewal_discount_rate: selected.value.renewal_discount_rate,
    margin_floor: selected.value.margin_floor,
    account_priority: [...selected.value.account_priority],
    description: selected.value.description || "",
    effective_at: selected.value.effective_at,
    templates: templates.value.map(cloneTemplate),
  });
  dialogVisible.value = true;
}
function addTemplate() {
  form.templates.push(blankTemplate());
}
function releaseTotal(item: PricingVersionForm["templates"][number]) {
  return item.release_plan.reduce((sum, release) => sum + release.amount, 0);
}
async function save() {
  if (saving.value) return;
  form.version = form.version.trim();
  form.name = form.name.trim();
  if (!form.version || form.name.length < 2 || !form.templates.length)
    return ElMessage.warning("请完整填写版本和套餐");
  for (const [index, item] of form.templates.entries()) {
    item.code = item.code.trim();
    item.name = item.name.trim();
    if (item.code.length < 2 || item.name.length < 2) {
      editor.value?.revealTemplate(index);
      return ElMessage.warning(`请完整填写套餐 ${index + 1} 的名称与编码（至少 2 个字符）`);
    }
    if (item.entitlement_kind === "duration") {
      item.total_credits = 0;
      item.release_plan = [];
      item.requires_active_subscription = false;
      continue;
    }
    if (
      !item.total_credits ||
      !item.release_plan.length ||
      releaseTotal(item) !== item.total_credits
    ) {
      editor.value?.revealTemplate(index, "credits");
      return ElMessage.warning(`「${item.name}」的释放合计必须等于总积分`);
    }
  }
  if (new Set(form.templates.map((item) => item.code)).size !== form.templates.length)
    return ElMessage.warning("套餐编码不能重复");
  form.templates.forEach((item, index) => (item.order = index + 1));
  saving.value = true;
  try {
    const response = editingId.value
      ? await BillingAPI.updateVersion(editingId.value, form)
      : await BillingAPI.createVersion(form);
    dialogVisible.value = false;
    selected.value = undefined;
    await load(response.data.data.id);
  } finally {
    saving.value = false;
  }
}
async function publish() {
  const target = selected.value;
  if (!target?.id || target.status === "published" || mutating.value) return;
  try {
    await ElMessageBox.confirm(
      `发布「${target.name}」后，将自动归档全平台当前已发布版本。`,
      "发布价格体系",
      { type: "warning", confirmButtonText: "确认发布", cancelButtonText: "取消" }
    );
  } catch {
    return;
  }
  mutating.value = true;
  try {
    await BillingAPI.publishVersion(target.id);
    await load(target.id);
  } finally {
    mutating.value = false;
  }
}
async function removeVersion() {
  const target = selected.value;
  if (!target?.id || target.status === "published" || mutating.value) return;
  try {
    await ElMessageBox.confirm(
      `删除「${target.name}（${target.version}）」及其 ${target.template_count} 个套餐模板？有关联刊例或定价策略的版本需先处理关联数据。`,
      "删除价格体系",
      { type: "warning", confirmButtonText: "确认删除", cancelButtonText: "取消" }
    );
  } catch {
    return;
  }
  mutating.value = true;
  try {
    await BillingAPI.deleteVersion(target.id);
    await load();
  } finally {
    mutating.value = false;
  }
}
onMounted(load);
watch(dialogVisible, (visible) => clientAppStore.markDirty("pricing-standard-editor", visible));
onUnmounted(() => clientAppStore.markDirty("pricing-standard-editor", false));
</script>

<style scoped>
.ops-page {
  box-sizing: border-box;
  display: flex;
  padding: 12px;
  overflow: hidden;
  background: var(--app-bg);
}

.layout {
  display: grid;
  flex: 1;
  grid-template-columns: 224px minmax(0, 1fr);
  gap: 16px;
  min-height: 0;
}

.version-list,
.content-card {
  min-height: 0;
  overflow: auto;
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 14px;
}

.version-list {
  padding: 12px;
}

.version-list-heading {
  display: flex;
  justify-content: space-between;
  padding: 12px 10px 20px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.version-list-heading span {
  font-variant-numeric: tabular-nums;
}

.version-list button {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 10px 6px;
  width: 100%;
  padding: 14px 12px;
  margin-bottom: 8px;
  color: var(--el-text-color-primary);
  text-align: left;
  cursor: pointer;
  background: transparent;
  border: 1px solid transparent;
  border-radius: 10px;
}

.version-list button:hover {
  background: var(--el-fill-color-light);
}

.version-list button.active {
  background: var(--el-color-primary-light-9);
  border-color: var(--el-color-primary-light-7);
}

.version-list button:focus-visible {
  outline: 2px solid var(--el-color-primary);
  outline-offset: 2px;
}

.version-title {
  display: grid;
  gap: 6px;
  min-width: 0;
}

.version-title strong {
  font-size: 14px;
  overflow-wrap: anywhere;
}

.version-list small,
.version-list em {
  font-size: 11px;
  font-style: normal;
  color: var(--el-text-color-secondary);
}

.version-list em {
  grid-column: 1 / -1;
}

.version-status {
  font-size: 10px;
  color: var(--el-text-color-secondary);
}

.version-status.published {
  color: var(--el-color-primary);
}

.content-card {
  padding: 30px;
}

.content-head {
  display: flex;
  flex-wrap: wrap;
  gap: 20px;
  align-items: center;
  justify-content: space-between;
  padding-bottom: 28px;
  border-bottom: 1px solid var(--el-border-color-lighter);
}

.preview-eyebrow {
  margin-bottom: 9px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.content-head h2 {
  margin: 0;
  font-size: 24px;
  font-weight: 600;
  letter-spacing: -0.5px;
}

.content-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.content-actions :deep(.el-button + .el-button) {
  margin-left: 0;
}

@media (width <= 1100px) {
  .layout {
    grid-template-columns: 196px minmax(0, 1fr);
  }

  .content-card {
    padding: 24px;
  }
}
@media (width <= 700px) {
  .layout {
    grid-template-columns: 1fr;
    overflow: auto;
  }

  .version-list {
    max-height: 220px;
  }

  .content-card {
    padding: 20px;
    overflow: visible;
  }

  .content-head h2 {
    font-size: 21px;
  }
}
</style>
