<template>
  <main class="fa-full-height">
    <FaSearchBar
      v-if="currentApp"
      v-show="showSearchBar"
      :model-value="query"
      :items="searchItems"
      :is-expand="false"
      :show-expand="false"
      @update:model-value="Object.assign(query, $event)"
      @search="search"
      @reset="reset"
    />
    <ElCard
      v-if="currentApp"
      class="fa-table-card"
      :style="{ 'margin-top': showSearchBar ? '12px' : '0' }"
    >
      <FaTableHeader
        v-model:columns="columnChecks"
        v-model:showSearchBar="showSearchBar"
        :loading="loading"
        @refresh="load"
        ><template #left
          ><ElButton
            v-hasPerm="['workspace:budget:pricing:create']"
            type="primary"
            :disabled="!plans.length"
            @click="openCreate"
            ><FaSvgIcon icon="ri:add-line" />新建策略版本</ElButton
          ></template
        ></FaTableHeader
      >
      <FaTable
        :loading="loading"
        :data="pageRows"
        :columns="columns"
        :pagination="pagination"
        @pagination:size-change="changeSize"
        @pagination:current-change="changePage"
      />
    </ElCard>
    <ElCard v-else class="fa-table-card"><ElEmpty description="请先在顶栏选择客户端" /></ElCard>

    <ElDialog v-model="visible" :title="dialogTitle" width="min(1400px, 97vw)" destroy-on-close>
      <ElForm label-position="top" :disabled="readOnly || saving">
        <div class="form-grid">
          <ElFormItem label="策略名称"><ElInput v-model="form.name" /></ElFormItem
          ><ElFormItem label="版本号"
            ><ElInput v-model="form.version" placeholder="例如 2026.09-A" /></ElFormItem
          ><ElFormItem label="价格体系"
            ><ElSelect v-model="form.pricing_version_id"
              ><ElOption
                v-for="item in versions.filter(
                  (x) => x.status === 'published' || x.id === form.pricing_version_id
                )"
                :key="item.id"
                :label="`${item.name}（${item.version}）`"
                :value="item.id || 0" /></ElSelect></ElFormItem
          ><ElFormItem label="适用范围"
            ><ElSelect v-model="form.scope_type"
              ><ElOption label="全部用户" value="all" /><ElOption
                label="新用户"
                value="new" /><ElOption label="等级（R / A / 旧LV）" value="level" /><ElOption
                label="动态分群"
                value="segment" /><ElOption label="指定用户" value="users" /></ElSelect
          ></ElFormItem>
        </div>
        <ElFormItem v-if="form.scope_type === 'new'" label="注册天数"
          ><ElInputNumber v-model="newDays" :min="1" :max="365"
        /></ElFormItem>
        <ElFormItem v-if="form.scope_type === 'level'" label="用户等级"
          ><ElSelect v-model="levelCodes" multiple
            ><ElOption v-for="item in levels" :key="item" :label="item" :value="item" /></ElSelect
        ></ElFormItem>
        <ElFormItem v-if="form.scope_type === 'segment'" label="动态分群"
          ><ElSelect v-model="segmentId"
            ><ElOption
              v-for="item in segments"
              :key="item.id"
              :label="`${item.name}（${item.matched_count}人）`"
              :value="item.id || 0" /></ElSelect
        ></ElFormItem>
        <ElFormItem v-if="form.scope_type === 'users'" label="指定用户"
          ><ElSelect v-model="userIds" multiple filterable
            ><ElOption
              v-for="item in users"
              :key="item.id"
              :label="item.display_name || item.username"
              :value="item.id || 0" /></ElSelect
        ></ElFormItem>
        <div class="form-grid">
          <ElFormItem label="生效区间" class="range"
            ><ElDatePicker
              v-model="dateRange"
              type="datetimerange"
              value-format="YYYY-MM-DDTHH:mm:ssZ"
              start-placeholder="开始时间"
              end-placeholder="结束时间" /></ElFormItem
          ><ElFormItem v-if="!readOnly" label="保存状态"
            ><ElRadioGroup v-model="form.status"
              ><ElRadio value="inactive">保存草稿</ElRadio
              ><ElRadio value="active">立即上架</ElRadio></ElRadioGroup
            ></ElFormItem
          >
        </div>
        <div class="item-head">
          <strong>刊例定价项</strong
          ><ElButton v-if="!readOnly" link type="primary" @click="addItem">添加刊例项</ElButton>
        </div>
        <p v-if="localMode" class="cost-help">
          时长套餐仅配置销售价格和折扣，不涉及模型成本或积分；不同天数套餐购买后累计期限。
        </p>
        <p v-else-if="!readOnly" class="cost-help">
          付费刊例的允许模型成本按执行价 ×（1 −
          目标毛利率）计算；零元刊例请填写成本预算，留空时使用产品刊例预算。购买类型选“全部”时，预览显示首购价，保存后分别计算首购和续费。
        </p>
        <ElSelect v-model="planTypeFilter" clearable placeholder="筛选候选套餐类型" class="mb-4">
          <ElOption label="含 token 费用" value="credits" />
          <ElOption label="token 自费" value="duration" />
        </ElSelect>
        <ElTable :data="form.items" border size="small">
          <ElTableColumn label="刊例" min-width="170" fixed="left"
            ><template #default="{ row }"
              ><ElSelect v-model="row.catalog_plan_id" @change="row.allowed_cost_yuan = undefined"
                ><ElOption
                  v-for="item in plans.filter(
                    (plan) =>
                      !planTypeFilter || (plan.entitlement_kind ?? 'credits') === planTypeFilter
                  )"
                  :key="item.id"
                  :label="`${item.name} · ${billingModeLabel(item.entitlement_kind ?? 'credits')}`"
                  :value="item.id || 0" /></ElSelect></template
          ></ElTableColumn>
          <ElTableColumn label="购买类型" width="145"
            ><template #default="{ row }"
              ><ElSelect v-model="row.purchase_type"
                ><ElOption label="首购" value="first" /><ElOption
                  label="续费"
                  value="renewal" /><ElOption label="全部" value="all" /></ElSelect></template
          ></ElTableColumn>
          <ElTableColumn label="折扣系数" width="150"
            ><template #default="{ row }"
              ><ElInputNumber
                v-model="row.discount_rate"
                :min="0.01"
                :max="1"
                :step="0.05" /></template
          ></ElTableColumn>
          <ElTableColumn v-if="!localMode" label="目标毛利率%" width="160"
            ><template #default="{ row }"
              ><span v-if="durationItem(Number(row.catalog_plan_id))">不适用</span
              ><ElInputNumber v-else v-model="row.margin_rate" :min="0" :max="99" /></template
          ></ElTableColumn>
          <ElTableColumn label="执行价" width="110"
            ><template #default="{ row }">¥{{ calculation(row).price }}</template></ElTableColumn
          >
          <ElTableColumn v-if="!localMode" label="允许模型成本（元）" width="190"
            ><template #default="{ row }">
              <ElInputNumber
                v-if="
                  !durationItem(Number(row.catalog_plan_id)) && !readOnly && needsCostBudget(row)
                "
                v-model="row.allowed_cost_yuan"
                :min="0.0001"
                :precision="4"
                :step="0.1"
                :controls="false"
                :placeholder="budgetPlaceholder(row)"
              />
              <span v-else>{{
                durationItem(Number(row.catalog_plan_id)) ? "不适用" : `¥${calculation(row).cost}`
              }}</span>
            </template></ElTableColumn
          >
          <ElTableColumn v-if="!localMode" label="每元成本扣积分" width="145"
            ><template #default="{ row }">{{
              durationItem(Number(row.catalog_plan_id)) ? "不适用" : calculation(row).rate
            }}</template></ElTableColumn
          >
          <ElTableColumn v-if="!readOnly" label="操作" width="70" fixed="right"
            ><template #default="{ $index }"
              ><ElButton link type="danger" @click="form.items.splice($index, 1)"
                >移除</ElButton
              ></template
            ></ElTableColumn
          >
        </ElTable>
        <ElCollapse class="cost-panel"
          ><ElCollapseItem v-if="!localMode" title="供应商模型采购成本测算" name="cost"
            ><ElTable :data="models" size="small"
              ><ElTableColumn prop="display_name" label="模型" /><ElTableColumn
                label="输入成本/百万Token"
                ><template #default="{ row }"
                  >¥{{ row.input_cost_per_million }}</template
                ></ElTableColumn
              ><ElTableColumn label="输出成本/百万Token"
                ><template #default="{ row }"
                  >¥{{ row.output_cost_per_million }}</template
                ></ElTableColumn
              ><ElTableColumn label="按首项每百万输入扣积分"
                ><template #default="{ row }">{{
                  Math.ceil(
                    row.input_cost_per_million * Number(calculation(form.items[0]).rate || 0)
                  ).toLocaleString()
                }}</template></ElTableColumn
              ><ElTableColumn label="单位直接产值"
                ><template #default="{ row }"
                  >¥{{ directRevenue(row.input_cost_per_million) }}</template
                ></ElTableColumn
              ></ElTable
            ></ElCollapseItem
          ></ElCollapse
        >
      </ElForm>
      <template #footer
        ><ElButton :disabled="saving" @click="visible = false">{{
          readOnly ? "关闭" : "取消"
        }}</ElButton
        ><ElButton v-if="!readOnly" type="primary" :loading="saving" @click="save"
          >保存策略</ElButton
        ></template
      >
    </ElDialog>
  </main>
</template>

<script setup lang="ts">
import { billingModeLabel, type BillingMode } from "@/api/module_client/app";
import { computed, reactive, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useTableColumns } from "@/hooks/core/useTableColumns";
import { ElMessage, ElMessageBox } from "element-plus";
import BillingAPI, {
  type CatalogPlan,
  type PricingStrategy,
  type PricingStrategyForm,
  type PricingStrategyItem,
  type PricingVersion,
} from "@/api/module_billing";
import ClientUserAPI, { type ClientUserInfo, type UserSegment } from "@/api/module_client/user";
import ModelGatewayAPI, { type CatalogModel } from "@/api/module_model_gateway";
import type { SearchFormItem } from "@/components/forms/fa-search-bar/index.vue";
import FaTableHeader from "@/components/tables/fa-table-header/index.vue";
import { useClientAppStore } from "@stores";
import { renderTableOperationCell } from "@utils";
defineOptions({ name: "BudgetPricingStrategy" });
const { currentApp } = storeToRefs(useClientAppStore());
const planTypeFilter = ref<BillingMode | "">("");
const localMode = computed(
  () => form.items.length > 0 && form.items.every((item) => durationItem(item.catalog_plan_id))
);
const durationItem = (id: number) =>
  plans.value.find((plan) => plan.id === id)?.entitlement_kind === "duration";
const plans = ref<CatalogPlan[]>([]),
  strategies = ref<PricingStrategy[]>([]),
  versions = ref<PricingVersion[]>([]),
  segments = ref<UserSegment[]>([]),
  users = ref<ClientUserInfo[]>([]),
  models = ref<CatalogModel[]>([]);
const query = reactive({ keyword: "", status: "", scope_type: "" }),
  submitted = ref({ ...query }),
  pageNo = ref(1),
  pageSize = ref(10),
  showSearchBar = ref(true),
  loading = ref(false),
  saving = ref(false),
  visible = ref(false),
  editingId = ref<number>(),
  readOnly = ref(false),
  dateRange = ref<[string, string] | null>(null),
  levelCodes = ref<string[]>([]),
  segmentId = ref<number>(),
  userIds = ref<number[]>([]),
  newDays = ref(30);
const dialogTitle = computed(() =>
  readOnly.value ? "查看定价策略版本" : editingId.value ? "编辑定价策略版本" : "新建定价策略版本"
);
const levels = ["R1", "R2", "R3", "A1", "A2", "A3", "LV1", "LV2", "LV3", "LV4", "LV5"];
const form = reactive<PricingStrategyForm>({
  catalog_plan_id: 0,
  name: "",
  version: "",
  pricing_version_id: undefined,
  scope_type: "all",
  scope_value: {},
  purchase_type: "all",
  starts_at: "",
  ends_at: "",
  status: "inactive",
  description: "",
  items: [],
});
const searchItems: SearchFormItem[] = [
  { label: "策略名称", key: "keyword", type: "input", props: { clearable: true }, span: 8 },
  {
    label: "适用范围",
    key: "scope_type",
    type: "select",
    props: {
      clearable: true,
      options: [
        { label: "全部用户", value: "all" },
        { label: "新用户", value: "new" },
        { label: "等级（R / A / 旧LV）", value: "level" },
        { label: "动态分群", value: "segment" },
        { label: "指定用户", value: "users" },
      ],
    },
    span: 8,
  },
  {
    label: "状态",
    key: "status",
    type: "select",
    props: {
      clearable: true,
      options: [
        { label: "执行中", value: "active" },
        { label: "已下架", value: "inactive" },
      ],
    },
    span: 8,
  },
];
const filtered = computed(() =>
  strategies.value.filter(
    (x) =>
      (!submitted.value.keyword ||
        x.name.toLowerCase().includes(submitted.value.keyword.toLowerCase())) &&
      (!submitted.value.status || x.status === submitted.value.status) &&
      (!submitted.value.scope_type || x.scope_type === submitted.value.scope_type)
  )
);
const pageRows = computed(() =>
  filtered.value.slice((pageNo.value - 1) * pageSize.value, pageNo.value * pageSize.value)
);
const pagination = computed(() => ({
  current: pageNo.value,
  size: pageSize.value,
  total: filtered.value.length,
}));
const scopeName = (v: string) =>
  ({
    all: "全部用户",
    new: "新用户",
    level: "等级（R / A / 旧LV）",
    segment: "动态分群",
    users: "指定用户",
  })[v] || v;
const statusName = (v: string) => (v === "active" ? "执行中" : "已下架");
const { columnChecks, columns } = useTableColumns<PricingStrategy>(() => [
  { type: "globalIndex", width: 56, label: "序号" },
  { prop: "version", label: "版本号", width: 120 },
  { prop: "name", label: "策略名称", minWidth: 160 },
  { prop: "scope_type", label: "适用范围", width: 110, formatter: (r) => scopeName(r.scope_type) },
  { prop: "items", label: "刊例项", width: 90, formatter: (r) => `${r.items.length} 项` },
  { prop: "starts_at", label: "开始时间", width: 170 },
  { prop: "ends_at", label: "结束时间", width: 170 },
  { prop: "status", label: "状态", width: 90, formatter: (r) => statusName(r.status) },
  { prop: "published_at", label: "发布时间", width: 170 },
  {
    prop: "operation",
    label: "操作",
    width: 150,
    fixed: "right",
    align: "center",
    formatter: (r) =>
      renderTableOperationCell([
        {
          key: "view",
          label: "查看",
          artType: "view",
          perm: "workspace:budget:pricing:list",
          run: () => void openExisting(r, true),
        },
        {
          key: "edit",
          label: r.status === "active" ? "请先下架再编辑" : "编辑",
          artType: "edit",
          disabled: r.status === "active",
          perm: "workspace:budget:pricing:create",
          run: () => void openExisting(r, false),
        },
        {
          key: "status",
          label: r.status === "active" ? "下架" : "上架",
          artType: "custom",
          icon: r.status === "active" ? "ri:arrow-down-circle-line" : "ri:arrow-up-circle-line",
          iconColor: r.status === "active" ? "var(--el-color-warning)" : "var(--el-color-success)",
          perm: "workspace:budget:pricing:create",
          run: () => void toggle(r),
        },
        {
          key: "delete",
          label: r.status === "active" ? "请先下架再删除" : "删除",
          artType: "delete",
          disabled: r.status === "active",
          perm: "workspace:budget:pricing:create",
          run: () => void removeStrategy(r),
        },
      ]),
  },
]);
async function load() {
  if (!currentApp.value) return;
  loading.value = true;
  try {
    const [p, s, v, g, u, m] = await Promise.all([
      BillingAPI.plans(),
      BillingAPI.strategies(),
      BillingAPI.versions(),
      ClientUserAPI.segments(),
      ClientUserAPI.list({ page_no: 1, page_size: 100 }),
      ModelGatewayAPI.models(),
    ]);
    plans.value = p.data.data || [];
    strategies.value = s.data.data || [];
    versions.value = v.data.data || [];
    segments.value = g.data.data || [];
    users.value = u.data.data?.items || [];
    models.value = m.data.data || [];
  } finally {
    loading.value = false;
  }
}
function search(v: Record<string, unknown>) {
  submitted.value = {
    keyword: String(v.keyword || ""),
    status: String(v.status || ""),
    scope_type: String(v.scope_type || ""),
  };
  pageNo.value = 1;
}
function reset() {
  Object.assign(query, { keyword: "", status: "", scope_type: "" });
  submitted.value = { ...query };
  pageNo.value = 1;
}
function changeSize(v: number) {
  pageSize.value = v;
  pageNo.value = 1;
}
function changePage(v: number) {
  pageNo.value = v;
}
function addItem() {
  form.items.push({
    catalog_plan_id: plans.value[0]?.id || 0,
    purchase_type: "first",
    discount_rate: 1,
    margin_rate: 60,
  });
}
function openCreate() {
  editingId.value = undefined;
  readOnly.value = false;
  Object.assign(form, {
    catalog_plan_id: plans.value[0]?.id || 0,
    name: "",
    version: `V${new Date().toISOString().replace(/\D/g, "").slice(0, 17)}`,
    pricing_version_id: versions.value.find((x) => x.status === "published")?.id,
    scope_type: "all",
    scope_value: {},
    purchase_type: "all",
    starts_at: "",
    ends_at: "",
    status: "inactive",
    description: "",
    items: [],
  });
  dateRange.value = null;
  levelCodes.value = [];
  segmentId.value = undefined;
  userIds.value = [];
  newDays.value = 30;
  addItem();
  visible.value = true;
}
async function openExisting(row: PricingStrategy, view: boolean) {
  const response = await BillingAPI.strategy(Number(row.id));
  const detail = response.data.data;
  if (!detail) return;
  if (!view && detail.status === "active") return ElMessage.warning("请先下架策略再编辑");
  editingId.value = Number(detail.id);
  readOnly.value = view;
  Object.assign(form, {
    catalog_plan_id: detail.catalog_plan_id,
    name: detail.name,
    version: detail.version,
    pricing_version_id: detail.pricing_version_id,
    scope_type: detail.scope_type,
    scope_value: { ...detail.scope_value },
    purchase_type: detail.purchase_type,
    starts_at: detail.starts_at,
    ends_at: detail.ends_at,
    status: detail.status,
    description: detail.description,
    items: detail.items.map((item) => ({
      ...item,
      allowed_cost_yuan: view || needsCostBudget(item) ? item.allowed_cost_yuan : undefined,
    })),
  });
  dateRange.value = [detail.starts_at, detail.ends_at];
  newDays.value = Number(detail.scope_value.days || 30);
  levelCodes.value = Array.isArray(detail.scope_value.level_codes)
    ? detail.scope_value.level_codes.map(String)
    : [];
  segmentId.value = detail.scope_value.segment_id
    ? Number(detail.scope_value.segment_id)
    : undefined;
  userIds.value = Array.isArray(detail.scope_value.user_ids)
    ? detail.scope_value.user_ids.map(Number)
    : [];
  visible.value = true;
}
function needsCostBudget(item: Partial<PricingStrategyItem>) {
  if (localMode.value) return false;
  const plan = plans.value.find((x) => x.id === item.catalog_plan_id);
  if (!plan) return false;
  const prices =
    item.purchase_type === "all"
      ? [plan.one_time_price_fen, plan.recurring_price_fen]
      : [basePrice(item)];
  return prices.some((price) => Math.round(price * Number(item.discount_rate || 0)) === 0);
}
function budgetPlaceholder(item: Partial<PricingStrategyItem>) {
  const budget = plans.value.find((x) => x.id === item.catalog_plan_id)?.cost_budget_yuan;
  return budget ? `刊例预算 ${budget} 元` : "请输入大于 0 的成本";
}
function basePrice(item?: Partial<PricingStrategyItem>) {
  const plan = plans.value.find((x) => x.id === item?.catalog_plan_id);
  if (!plan) return 0;
  return item?.purchase_type === "renewal" ? plan.recurring_price_fen : plan.one_time_price_fen;
}
function calculation(item?: Partial<PricingStrategyItem>) {
  if (!item) return { price: "0.00", cost: "0.0000", rate: "0" };
  const plan = plans.value.find((x) => x.id === item.catalog_plan_id);
  const price =
    (readOnly.value
      ? Number(item.execution_price_fen || 0)
      : Math.round(basePrice(item) * Number(item.discount_rate || 0))) / 100;
  const cost = readOnly.value
    ? Number(item.allowed_cost_yuan || 0)
    : price === 0
      ? Number(item.allowed_cost_yuan ?? plan?.cost_budget_yuan ?? 0)
      : price * (1 - Number(item.margin_rate || 0) / 100);
  const rate = readOnly.value
    ? Number(item.credits_per_cost_yuan || 0)
    : cost > 0
      ? (plan?.total_credits || 0) / cost
      : 0;
  return { price: price.toFixed(2), cost: cost.toFixed(4), rate: rate.toFixed(2) };
}
function directRevenue(cost: number) {
  const rate = Number(calculation(form.items[0]).rate || 0);
  return rate ? (rate / 1000 - cost).toFixed(2) : "0.00";
}
async function save() {
  if (saving.value || readOnly.value) return;
  if (
    !form.name ||
    !form.version ||
    !form.pricing_version_id ||
    !dateRange.value ||
    !form.items.length
  )
    return ElMessage.warning("请完整填写策略版本和刊例项");
  for (const item of form.items) {
    const plan = plans.value.find((x) => x.id === item.catalog_plan_id);
    if (!plan) return ElMessage.warning("请选择有效的产品刊例");
    if (plan.entitlement_kind === "duration" && Number(calculation(item).price) <= 0)
      return ElMessage.warning("时长套餐执行价必须大于0");
    if (needsCostBudget(item) && !(Number(item.allowed_cost_yuan ?? plan.cost_budget_yuan) > 0))
      return ElMessage.warning(`${plan.name} 为零元刊例，请填写大于 0 的允许模型成本`);
  }
  const [starts_at, ends_at] = dateRange.value;
  let scope_value: Record<string, unknown> = {};
  if (form.scope_type === "new") scope_value = { days: newDays.value };
  if (form.scope_type === "level") scope_value = { level_codes: levelCodes.value };
  if (form.scope_type === "segment") scope_value = { segment_id: segmentId.value };
  if (form.scope_type === "users") scope_value = { user_ids: userIds.value };
  saving.value = true;
  try {
    const payload: PricingStrategyForm = {
      ...form,
      catalog_plan_id: form.items[0]!.catalog_plan_id,
      starts_at,
      ends_at,
      scope_value,
      items: form.items.map((item) => ({
        catalog_plan_id: item.catalog_plan_id,
        purchase_type: item.purchase_type,
        discount_rate: item.discount_rate,
        margin_rate: item.margin_rate,
        allowed_cost_yuan: needsCostBudget(item) ? item.allowed_cost_yuan : undefined,
        remark: item.remark,
      })),
    };
    if (editingId.value) await BillingAPI.updateStrategy(editingId.value, payload);
    else await BillingAPI.createStrategy(payload);
    visible.value = false;
    await load();
  } finally {
    saving.value = false;
  }
}
async function toggle(row: PricingStrategy) {
  if (row.status !== "active")
    await ElMessageBox.confirm(
      "上架后会自动下架当前执行中的策略，已购权益仍按原快照结算。",
      "上架策略",
      { type: "warning" }
    );
  await BillingAPI.setStrategyStatus(
    Number(row.id),
    row.status === "active" ? "inactive" : "active"
  );
  await load();
}
async function removeStrategy(row: PricingStrategy) {
  try {
    await ElMessageBox.confirm(
      `确定删除策略“${row.name}（${row.version || "未编号"}）”？删除后不再显示，已购权益仍按原快照结算。`,
      "删除定价策略",
      { type: "warning" }
    );
  } catch {
    return;
  }
  await BillingAPI.deleteStrategy(Number(row.id));
  await load();
  pageNo.value = Math.min(
    pageNo.value,
    Math.max(1, Math.ceil(filtered.value.length / pageSize.value))
  );
}
watch(
  () => currentApp.value?.id,
  () => {
    visible.value = false;
    pageNo.value = 1;
    void load();
  },
  { immediate: true }
);
</script>
<style scoped>
.form-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 0 14px;
}

.form-grid .range {
  grid-column: span 3;
}

.el-select,
.el-input-number {
  width: 100%;
}

.item-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin: 8px 0;
}

.cost-panel {
  margin-top: 16px;
}

.cost-help {
  margin: 0 0 12px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
@media (width<=900px) {
  .form-grid {
    grid-template-columns: 1fr 1fr;
  }

  .form-grid .range {
    grid-column: span 2;
  }
}
</style>
