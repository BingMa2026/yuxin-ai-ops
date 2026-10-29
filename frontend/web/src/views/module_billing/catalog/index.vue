<template>
  <main class="ops-page fa-full-height">
    <FaSearchBar
      v-if="currentApp"
      v-show="showSearchBar"
      :model-value="query"
      :items="searchItems"
      :is-expand="false"
      :show-expand="false"
      @update:model-value="Object.assign(query, $event)"
      @search="handleSearch"
      @reset="handleReset"
    />
    <ElCard
      v-if="currentApp"
      class="fa-table-card"
      :style="{ 'margin-top': showSearchBar ? '12px' : '0' }"
    >
      <FaTableHeader
        class="catalog-header"
        v-model:columns="columnChecks"
        v-model:showSearchBar="showSearchBar"
        :loading="loading"
        @refresh="load"
      >
        <template #left>
          <div class="catalog-toolbar">
            <ElRadioGroup v-model="typeFilter" aria-label="刊例类型" @change="handleTypeChange">
              <ElRadioButton value="credits">含 token 费用</ElRadioButton>
              <ElRadioButton value="duration">token 自费</ElRadioButton>
            </ElRadioGroup>
            <ElButton
              v-hasPerm="['workspace:budget:rate-card:create']"
              type="primary"
              @click="openCreate"
            >
              <FaSvgIcon icon="ri:add-line" />新增刊例
            </ElButton>
          </div>
        </template>
      </FaTableHeader>
      <FaTable
        :loading="loading"
        :data="pageRows"
        :columns="columns"
        :pagination="pagination"
        @pagination:size-change="handleSizeChange"
        @pagination:current-change="handleCurrentChange"
      />
    </ElCard>
    <ElCard v-else class="fa-table-card"><ElEmpty description="请先在顶栏选择客户端" /></ElCard>

    <ElDialog
      v-model="dialogVisible"
      :title="editing?.id ? '编辑刊例' : '新增刊例'"
      width="min(760px, 94vw)"
      destroy-on-close
    >
      <ElForm label-position="top">
        <ElFormItem label="权益类型">
          <ElRadioGroup v-model="form.entitlement_kind" :disabled="!!editing" @change="changeKind">
            <ElRadio value="credits" :disabled="currentApp?.service_mode === 'duration_only'">
              含 token 费用
            </ElRadio>
            <ElRadio value="duration" :disabled="currentApp?.service_mode === 'credits_only'">
              token 自费
            </ElRadio>
          </ElRadioGroup>
        </ElFormItem>
        <ElAlert
          v-if="isDuration"
          title="时长套餐：积分固定为0，充值增加订阅天数，用户自行配置模型 Key。"
          type="info"
          :closable="false"
          class="mb-4"
        />
        <div v-if="!editing" class="form-grid">
          <ElFormItem label="价格版本">
            <ElSelect v-model="form.pricing_version_id" @change="loadTemplates">
              <ElOption
                v-for="item in versions.filter((value) => value.status === 'published')"
                :key="item.id"
                :label="`${item.name} (${item.version})`"
                :value="item.id || 0"
              />
            </ElSelect>
          </ElFormItem>
          <ElFormItem label="套用模板">
            <ElSelect
              v-model="form.template_id"
              clearable
              :loading="loadingTemplates"
              :disabled="loadingTemplates"
              @change="applyTemplate"
            >
              <ElOption
                v-for="item in templates"
                :key="item.id"
                :label="item.name"
                :value="item.id || 0"
              />
            </ElSelect>
          </ElFormItem>
        </div>
        <div class="form-grid">
          <ElFormItem label="刊例名称"><ElInput v-model="form.name" /></ElFormItem>
          <ElFormItem label="刊例编码"
            ><ElInput v-model="form.code" :disabled="!!editing"
          /></ElFormItem>
          <ElFormItem v-if="!isDuration" label="项目类型"
            ><ElSelect v-model="form.plan_type"
              ><ElOption label="订阅套餐" value="subscription" /><ElOption
                label="流量积分包"
                value="credit_pack" /></ElSelect
          ></ElFormItem>
          <ElFormItem label="首购价（分）">
            <ElInputNumber v-model="form.one_time_price_fen" :min="0" controls-position="right" />
          </ElFormItem>
          <ElFormItem label="续费价（分）">
            <ElInputNumber v-model="form.recurring_price_fen" :min="0" controls-position="right" />
          </ElFormItem>
          <ElFormItem :label="isDuration ? '订阅天数' : '权益周期（天）'">
            <ElInputNumber
              v-model="form.benefit_period_days"
              :min="1"
              :max="3650"
              controls-position="right"
            />
          </ElFormItem>
          <ElFormItem v-if="!isDuration" label="积分有效期（天）">
            <ElInputNumber v-model="form.credit_valid_days" :min="1" controls-position="right" />
          </ElFormItem>
          <ElFormItem label="排序">
            <ElInputNumber v-model="form.order" :min="0" controls-position="right" />
          </ElFormItem>
          <ElFormItem v-if="!isDuration" label="零元项目允许成本（元）"
            ><ElInputNumber
              v-model="form.cost_budget_yuan"
              :min="0.01"
              :disabled="form.one_time_price_fen > 0"
          /></ElFormItem>
          <ElFormItem v-if="!isDuration" label="需有效订阅"
            ><ElSwitch
              v-model="form.requires_active_subscription"
              :disabled="form.plan_type === 'credit_pack'"
          /></ElFormItem>
        </div>
        <ElFormItem v-if="!isDuration" label="总算力积分">
          <ElInputNumber
            v-model="form.total_credits"
            :min="1"
            controls-position="right"
            @change="syncRelease"
          />
        </ElFormItem>
        <div v-if="!isDuration" class="release-list">
          <div class="release-head">
            <strong>积分释放计划</strong
            ><ElButton
              link
              type="primary"
              @click="
                form.release_plan.push({
                  offset_day: 0,
                  amount: 1,
                  account_type: form.plan_type === 'credit_pack' ? 'traffic_pack' : 'current_cycle',
                })
              "
              >添加批次</ElButton
            >
          </div>
          <div v-for="(item, index) in form.release_plan" :key="index" class="release-row">
            <ElInputNumber v-model="item.offset_day" :min="0" /><span>天后</span
            ><ElInputNumber v-model="item.amount" :min="1" /><span>积分</span
            ><ElSelect v-model="item.account_type"
              ><ElOption label="活动赠送" value="activity_reward" /><ElOption
                label="企业共享"
                value="enterprise_pool" /><ElOption label="人工调整" value="manual" /><ElOption
                label="当期权益"
                value="current_cycle" /><ElOption
                label="月度储备"
                value="monthly_reserve" /><ElOption
                label="流量积分包"
                value="traffic_pack" /></ElSelect
            ><ElButton
              v-if="form.release_plan.length > 1"
              link
              type="danger"
              @click="form.release_plan.splice(index, 1)"
              >移除</ElButton
            >
          </div>
        </div>
        <ElFormItem label="权益说明（每行一项）">
          <ElInput
            v-model="benefitsText"
            type="textarea"
            :rows="3"
            placeholder="填写功能或服务，积分数量和有效期由配置展示"
          />
        </ElFormItem>
      </ElForm>
      <template #footer>
        <ElButton @click="dialogVisible = false">取消</ElButton>
        <ElButton type="primary" :loading="saving" :disabled="loadingTemplates" @click="save"
          >保存</ElButton
        >
      </template>
    </ElDialog>
  </main>
</template>

<script setup lang="ts">
import { billingModeLabel, type BillingMode } from "@/api/module_client/app";
import { ElMessage, ElMessageBox, ElTag } from "element-plus";
import { catalogTemplateFields } from "./template-form";
import BillingAPI, {
  type CatalogPlan,
  type CatalogPlanForm,
  type PricingTemplate,
  type PricingVersion,
} from "@/api/module_billing";
import type { SearchFormItem } from "@/components/forms/fa-search-bar/index.vue";
import FaTableHeader from "@/components/tables/fa-table-header/index.vue";
import { useClientAppStore } from "@stores";
import { renderTableOperationCell, type TableOperationAction } from "@utils";

defineOptions({ name: "BudgetProductRateCard" });

const clientAppStore = useClientAppStore();
const { currentApp } = storeToRefs(clientAppStore);
const plans = ref<CatalogPlan[]>([]);
const versions = ref<PricingVersion[]>([]);
const templates = ref<PricingTemplate[]>([]);
const loadingTemplates = ref(false);
let templateRequestId = 0;
const typeFilter = ref<BillingMode>("credits");
let listRequestId = 0;
const query = reactive({ keyword: "", status: "" });
const submittedQuery = ref({ keyword: "", status: "" });
const pageNo = ref(1);
const pageSize = ref(10);
const showSearchBar = ref(true);
const loading = ref(false);
const saving = ref(false);
const dialogVisible = ref(false);
const editing = ref<CatalogPlan>();
const benefitsText = ref("");

const emptyForm = (): CatalogPlanForm => ({
  entitlement_kind: currentApp.value?.service_mode === "duration_only" ? "duration" : "credits",
  pricing_version_id: 0,
  template_id: undefined,
  tier_code: undefined,
  code: "",
  name: "",
  plan_type: "subscription",
  tier_order: 999,
  one_time_price_fen: 0,
  recurring_price_fen: 0,
  benefit_period_days: 30,
  total_credits: currentApp.value?.service_mode === "duration_only" ? 0 : 1000,
  release_plan:
    currentApp.value?.service_mode === "duration_only"
      ? []
      : [{ offset_day: 0, amount: 1000, account_type: "current_cycle" }],
  credit_valid_days: 30,
  benefits: [],
  requires_active_subscription: false,
  cost_budget_yuan: undefined,
  order: 999,
  status: "draft",
});
const form = reactive<CatalogPlanForm>(emptyForm());
const isDuration = computed(() => form.entitlement_kind === "duration");
const money = (value: number) => (value / 100).toFixed(2);

const searchItems: SearchFormItem[] = [
  {
    label: "刊例名称",
    key: "keyword",
    type: "input",
    placeholder: "请输入名称或编码",
    props: { clearable: true },
    span: 8,
  },
  {
    label: "状态",
    key: "status",
    type: "select",
    props: {
      placeholder: "请选择状态",
      clearable: true,
      options: [
        { label: "草稿", value: "draft" },
        { label: "销售中", value: "on_sale" },
        { label: "已下架", value: "off_sale" },
      ],
    },
    span: 8,
  },
];

const filteredRows = computed(() => {
  const keyword = submittedQuery.value.keyword.trim().toLowerCase();
  return plans.value.filter(
    (row) =>
      (!keyword ||
        row.name.toLowerCase().includes(keyword) ||
        row.code.toLowerCase().includes(keyword)) &&
      (!submittedQuery.value.status || row.status === submittedQuery.value.status)
  );
});
const pageRows = computed(() => {
  const start = (pageNo.value - 1) * pageSize.value;
  return filteredRows.value.slice(start, start + pageSize.value);
});
const pagination = computed(() => ({
  current: pageNo.value,
  size: pageSize.value,
  total: filteredRows.value.length,
}));

function rowActions(row: CatalogPlan): TableOperationAction[] {
  return [
    {
      key: "edit",
      label: "编辑",
      artType: "edit",
      perm: "workspace:budget:rate-card:create",
      run: () => openEdit(Number(row.id)),
    },
    {
      key: "status",
      label: row.status === "on_sale" ? "下架" : "上架",
      artType: "custom",
      icon: row.status === "on_sale" ? "ri:arrow-down-circle-line" : "ri:arrow-up-circle-line",
      iconColor: row.status === "on_sale" ? "var(--el-color-warning)" : "var(--el-color-success)",
      perm: "workspace:budget:rate-card:create",
      run: () => void setStatus(Number(row.id), row.status === "on_sale" ? "off_sale" : "on_sale"),
    },
  ];
}

const { columnChecks, columns } = useTableColumns<CatalogPlan>(() => [
  { type: "globalIndex", width: 56, label: "序号" },
  {
    prop: "entitlement_kind",
    label: "权益类型",
    width: 140,
    formatter: (row: CatalogPlan) => billingModeLabel(row.entitlement_kind ?? "credits"),
  },
  { prop: "name", label: "套餐名称", minWidth: 150, showOverflowTooltip: true },
  { prop: "code", label: "套餐编码", minWidth: 130, showOverflowTooltip: true },
  {
    prop: "plan_type",
    label: "项目类型",
    width: 110,
    formatter: (row: CatalogPlan) => (row.plan_type === "credit_pack" ? "流量积分包" : "订阅套餐"),
  },
  {
    prop: "one_time_price_fen",
    label: "首购价",
    width: 110,
    formatter: (row: CatalogPlan) => `¥${money(row.one_time_price_fen)}`,
  },
  {
    prop: "recurring_price_fen",
    label: "续费价",
    width: 110,
    formatter: (row: CatalogPlan) => `¥${money(row.recurring_price_fen)}`,
  },
  {
    prop: "benefit_period_days",
    label: "权益周期",
    width: 100,
    formatter: (row: CatalogPlan) => `${row.benefit_period_days} 天`,
  },
  {
    prop: "total_credits",
    label: "积分（计费权益）",
    width: 170,
    sortable: true,
    formatter: (row: CatalogPlan) =>
      `${row.total_credits.toLocaleString()} 积分${row.entitlement_kind === "duration" && row.total_credits !== 0 ? "（数据异常）" : ""}`,
  },
  { prop: "order", label: "排序", width: 80, sortable: true },
  {
    prop: "status",
    label: "状态",
    width: 90,
    formatter: (row: CatalogPlan) => {
      const status = {
        draft: { type: "info" as const, text: "草稿" },
        on_sale: { type: "success" as const, text: "销售中" },
        off_sale: { type: "danger" as const, text: "已下架" },
      }[row.status] || { type: "info" as const, text: row.status };
      return h(ElTag, { type: status.type, effect: "light" }, () => status.text);
    },
  },
  {
    prop: "operation",
    label: "操作",
    width: 150,
    fixed: "right",
    align: "center",
    formatter: (row: CatalogPlan) => renderTableOperationCell(rowActions(row)),
  },
]);

async function load() {
  const requestId = ++listRequestId;
  if (!currentApp.value) {
    plans.value = [];
    versions.value = [];
    loading.value = false;
    return;
  }
  loading.value = true;
  plans.value = [];
  try {
    const [planResponse, versionResponse] = await Promise.all([
      BillingAPI.plans(typeFilter.value),
      BillingAPI.versions(),
    ]);
    if (requestId !== listRequestId) return;
    plans.value = planResponse.data.data || [];
    versions.value = versionResponse.data.data || [];
  } catch {
    // The shared interceptor reports errors; keep the selected type empty.
  } finally {
    if (requestId === listRequestId) loading.value = false;
  }
}

function handleTypeChange() {
  pageNo.value = 1;
  void load();
}

function handleSearch(value: Record<string, unknown>) {
  submittedQuery.value = {
    keyword: String(value.keyword || ""),
    status: String(value.status || ""),
  };
  pageNo.value = 1;
}
function handleReset() {
  Object.assign(query, { keyword: "", status: "" });
  submittedQuery.value = { keyword: "", status: "" };
  pageNo.value = 1;
}
function handleSizeChange(size: number) {
  pageSize.value = size;
  pageNo.value = 1;
}
function handleCurrentChange(page: number) {
  pageNo.value = page;
}
function openCreate() {
  editing.value = undefined;
  Object.assign(form, emptyForm());
  if (currentApp.value?.service_mode === "user_choice") {
    form.entitlement_kind = typeFilter.value;
    changeKind();
  }
  benefitsText.value = isDuration.value
    ? "客户端使用权限\n自行配置模型"
    : "客户端核心能力\n模型服务";
  form.effective_from = undefined;
  form.effective_until = undefined;
  const published = versions.value.find((version) => version.status === "published");
  if (published?.id) {
    form.pricing_version_id = published.id;
    void loadTemplates(published.id);
  }
  dialogVisible.value = true;
}
function openEdit(id: number) {
  const row = plans.value.find((item) => item.id === id);
  if (!row) return;
  editing.value = row;
  Object.assign(form, JSON.parse(JSON.stringify(row)));
  benefitsText.value = row.benefits.join("\n");
  dialogVisible.value = true;
}
async function loadTemplates(value: number | string) {
  const requestId = ++templateRequestId;
  const id = Number(value);
  templates.value = [];
  form.template_id = undefined;
  loadingTemplates.value = false;
  if (!id) return;
  loadingTemplates.value = true;
  try {
    const response = await BillingAPI.templates(id);
    if (requestId === templateRequestId)
      templates.value = (response.data.data || []).filter(
        (item) => (item.entitlement_kind ?? "credits") === form.entitlement_kind
      );
  } catch {
    // Keep the list empty after the interceptor reports the failed request.
  } finally {
    if (requestId === templateRequestId) loadingTemplates.value = false;
  }
}
function changeKind() {
  if (isDuration.value) {
    form.plan_type = "subscription";
    form.total_credits = 0;
    form.release_plan = [];
    form.requires_active_subscription = false;
  } else {
    form.total_credits = 1000;
    form.release_plan = [{ offset_day: 0, amount: 1000, account_type: "current_cycle" }];
  }
  void loadTemplates(form.pricing_version_id);
}
function applyTemplate(value: number | string) {
  const item = templates.value.find((row) => row.id === Number(value));
  if (!item) return;
  Object.assign(form, catalogTemplateFields(item));
  benefitsText.value = item.benefits.join("\n");
}
function syncRelease() {
  if (form.release_plan.length === 1) {
    form.release_plan = [
      {
        offset_day: 0,
        amount: form.total_credits,
        account_type: form.plan_type === "credit_pack" ? "traffic_pack" : "current_cycle",
      },
    ];
  }
}
async function save() {
  if (saving.value) return;
  if (!form.name || !form.code || !form.pricing_version_id) {
    ElMessage.warning("请完整填写刊例");
    return;
  }
  form.benefits = benefitsText.value
    .split(/\r?\n/)
    .map((value) => value.trim())
    .filter(Boolean);
  form.requires_active_subscription =
    form.plan_type === "credit_pack" || form.requires_active_subscription;
  if (isDuration.value) {
    form.total_credits = 0;
    form.release_plan = [];
    form.requires_active_subscription = false;
    form.cost_budget_yuan = undefined;
  }
  saving.value = true;
  try {
    if (editing.value?.id) await BillingAPI.updatePlan(editing.value.id, form);
    else await BillingAPI.createPlan(form);
    dialogVisible.value = false;
    await load();
  } catch {
    // The request interceptor already presents the API error; keep the form for correction.
  } finally {
    saving.value = false;
  }
}
async function setStatus(id: number, status: CatalogPlan["status"]) {
  await ElMessageBox.confirm(
    status === "on_sale"
      ? "上架后客户端可立即购买，确认价格和权益规则已复核？"
      : "下架后不再接受新订单，已有订阅不受影响。",
    "确认操作",
    { type: "warning" }
  );
  await BillingAPI.updatePlan(id, { status });
  await load();
}

watch(
  () => [currentApp.value?.id, currentApp.value?.service_mode],
  () => {
    typeFilter.value = currentApp.value?.service_mode === "duration_only" ? "duration" : "credits";
    pageNo.value = 1;
    void load();
  },
  { immediate: true }
);
watch(dialogVisible, (visible) => clientAppStore.markDirty("catalog-plan-editor", visible));
onUnmounted(() => clientAppStore.markDirty("catalog-plan-editor", false));
</script>

<style scoped>
.ops-page {
  min-height: 0;
}

.catalog-header {
  margin-bottom: 16px;
}

.catalog-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px 16px;
}

.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0 14px;
}

.el-select,
.el-input-number {
  width: 100%;
}

.release-list {
  display: grid;
  gap: 8px;
  margin: 10px 0 16px;
}

.release-head,
.release-row {
  display: flex;
  gap: 10px;
  align-items: center;
}

.release-head {
  justify-content: space-between;
}

.release-row .el-input-number {
  width: 150px;
}

.release-row .el-select {
  width: 150px;
}

.release-row span {
  color: var(--el-text-color-secondary);
  white-space: nowrap;
}

@media (width <= 700px) {
  .form-grid {
    grid-template-columns: 1fr;
  }
}
</style>
