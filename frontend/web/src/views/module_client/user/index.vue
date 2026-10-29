<template>
  <main class="user-page fa-full-height">
    <FaSearchBar
      v-if="currentApp"
      v-show="showSearchBar"
      ref="searchBarRef"
      :model-value="query"
      :items="searchItems"
      :is-expand="false"
      :show-expand="true"
      :show-reset="true"
      :show-search="true"
      :disabled-search="false"
      :default-expanded="false"
      @update:model-value="Object.assign(query, $event)"
      @search="handleSearch"
      @reset="resetFilters"
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
      >
        <template #left>
          <ElSelect
            :model-value="query.segment"
            clearable
            class="segment-select"
            placeholder="全部用户"
            @change="selectSegment($event as string | undefined)"
          >
            <ElOption
              v-for="item in segments"
              :key="item.label"
              :label="item.label"
              :value="item.value"
            />
          </ElSelect>
          <ElSelect
            v-model="query.segment_id"
            clearable
            class="saved-segment-select"
            placeholder="已保存分群"
            @change="load"
          >
            <ElOption
              v-for="item in savedSegments"
              :key="item.id"
              :label="`${item.name}（${item.matched_count}人）`"
              :value="item.id || 0"
            />
          </ElSelect>
          <ElButton v-hasPerm="['workspace:user:management:update']" @click="saveSegment"
            >保存当前分群</ElButton
          >
        </template>
      </FaTableHeader>
      <FaTable
        :loading="loading"
        :data="rows"
        :columns="columns"
        :pagination="pagination"
        @pagination:size-change="handleSizeChange"
        @pagination:current-change="handleCurrentChange"
      />
    </ElCard>
    <ElCard v-else class="fa-table-card"><ElEmpty description="请先在顶栏选择客户端" /></ElCard>
    <ClientUserDetailDrawer
      v-model="detailVisible"
      :user="selected"
      :activity="activity"
      @add-tag="addTag"
      @remove-tag="removeTag"
    />
    <DurationAdjustmentDialog v-model="durationVisible" :user="durationUser" @saved="load" />
    <ElDialog v-model="creditVisible" title="调整用户积分" width="min(500px, 92vw)">
      <p class="dialog-user">用户：{{ creditUser?.display_name || creditUser?.username || "—" }}</p>
      <ElForm class="credit-form" label-position="top">
        <ElFormItem label="调整类型">
          <ElRadioGroup v-model="creditForm.direction">
            <ElRadioButton value="grant">赠送积分</ElRadioButton>
            <ElRadioButton value="deduct">扣减积分</ElRadioButton>
          </ElRadioGroup>
        </ElFormItem>
        <ElFormItem label="积分数量">
          <ElInputNumber
            v-model="creditForm.amount"
            :min="1"
            :step="100"
            controls-position="right"
          />
        </ElFormItem>
        <ElFormItem v-if="creditForm.direction === 'grant'" label="有效期（天）">
          <ElInputNumber
            v-model="creditForm.expires_in_days"
            :min="1"
            :max="3650"
            controls-position="right"
          />
        </ElFormItem>
        <ElFormItem label="调整原因">
          <ElInput
            v-model="creditForm.reason"
            type="textarea"
            :rows="3"
            maxlength="500"
            show-word-limit
            placeholder="必填，将写入积分流水"
          />
        </ElFormItem>
      </ElForm>
      <template #footer>
        <ElButton @click="creditVisible = false">取消</ElButton>
        <ElButton type="primary" :loading="creditSaving" @click="saveCredit">确认调整</ElButton>
      </template>
    </ElDialog>
    <ElDialog v-model="editVisible" class="client-user-edit-dialog" width="min(680px, 94vw)">
      <template #header>
        <div class="edit-dialog-heading">
          <ElAvatar
            :size="42"
            :src="editUser?.avatar"
            :style="
              editUser ? { backgroundColor: avatarColor(editUser), color: '#fff' } : undefined
            "
            >{{ (editUser?.display_name || editUser?.username || "用").slice(0, 1) }}</ElAvatar
          >
          <div>
            <strong>编辑用户资料</strong
            ><small>{{ editUser?.username }} · 资料修改不会影响登录账号</small>
          </div>
        </div>
      </template>
      <ElForm
        ref="editFormRef"
        :model="editForm"
        :rules="editRules"
        label-position="top"
        status-icon
      >
        <section class="form-section">
          <div class="form-section__title">
            <strong>基础身份</strong><span>用于运营识别和用户档案展示</span>
          </div>
          <div class="edit-grid">
            <ElFormItem prop="display_name" label="姓名或昵称"
              ><ElInput
                v-model="editForm.display_name"
                maxlength="64"
                placeholder="请输入姓名或昵称"
                clearable
            /></ElFormItem>
            <ElFormItem prop="company_name" label="企业名称"
              ><ElInput
                v-model="editForm.company_name"
                maxlength="128"
                placeholder="请输入企业或组织名称"
                clearable
            /></ElFormItem>
          </div>
        </section>
        <section class="form-section">
          <div class="form-section__title">
            <strong>联系方式</strong><span>便于工单跟进和重点用户服务</span>
          </div>
          <div class="edit-grid">
            <ElFormItem prop="mobile" label="手机号"
              ><ElInput
                v-model="editForm.mobile"
                maxlength="20"
                placeholder="请输入手机号"
                clearable
            /></ElFormItem>
            <ElFormItem prop="email" label="邮箱"
              ><ElInput
                v-model="editForm.email"
                maxlength="128"
                placeholder="name@example.com"
                clearable
            /></ElFormItem>
          </div>
        </section>
        <section class="form-section form-section--last">
          <div class="form-section__title">
            <strong>运营记录</strong><span>仅运营人员可见，不会展示给客户端用户</span>
          </div>
          <ElFormItem prop="description" label="运营备注"
            ><ElInput
              v-model="editForm.description"
              type="textarea"
              :rows="4"
              maxlength="1000"
              show-word-limit
              placeholder="记录用户特征、跟进重点或服务约定"
          /></ElFormItem>
        </section>
      </ElForm>
      <template #footer>
        <ElButton @click="editVisible = false">取消</ElButton>
        <ElButton type="primary" :loading="editSaving" @click="saveEdit">保存</ElButton>
      </template>
    </ElDialog>
  </main>
</template>

<script setup lang="ts">
import { ElAvatar, ElMessage, ElMessageBox, ElTag } from "element-plus";
import type { FormInstance, FormRules } from "element-plus";
import ClientUserAPI, {
  type ClientUserActivity,
  type ClientUserInfo,
  type ClientUserQuery,
  type UserSegment,
} from "@/api/module_client/user";
import BillingAPI, { type CatalogPlan } from "@/api/module_billing";
import type { SearchFormItem } from "@/components/forms/fa-search-bar/index.vue";
import type FaSearchBar from "@/components/forms/fa-search-bar/index.vue";
import FaTableHeader from "@/components/tables/fa-table-header/index.vue";
import { useClientAppStore } from "@stores";
import { renderTableOperationCell, type TableOperationAction } from "@utils";
import ClientUserDetailDrawer from "./components/ClientUserDetailDrawer.vue";
import DurationAdjustmentDialog from "./components/DurationAdjustmentDialog.vue";
import { billingColumnVisible, remainingSubscriptionTime } from "./billing-view";
defineOptions({ name: "ClientUserManagement" });
const clientAppStore = useClientAppStore();
const { currentApp } = storeToRefs(clientAppStore);
const localMode = computed(() => currentApp.value?.service_mode === "duration_only");
const query = reactive<ClientUserQuery>({ page_no: 1, page_size: 10 });
const rows = ref<ClientUserInfo[]>([]);
const total = ref(0);
const loading = ref(false);
const showSearchBar = ref(true);
const searchBarRef = ref<InstanceType<typeof FaSearchBar> | null>(null);
const detailVisible = ref(false);
const selected = ref<ClientUserInfo>();
const activity = ref<ClientUserActivity>();
const creditVisible = ref(false);
const durationVisible = ref(false);
const durationUser = ref<ClientUserInfo>();
const creditSaving = ref(false);
const creditUser = ref<ClientUserInfo>();
const plans = ref<CatalogPlan[]>([]);
const editVisible = ref(false);
const editSaving = ref(false);
const editUser = ref<ClientUserInfo>();
const editFormRef = ref<FormInstance>();
const savedSegments = ref<UserSegment[]>([]);
const editForm = reactive({
  display_name: "",
  company_name: "",
  mobile: "",
  email: "",
  description: "",
});
const editRules: FormRules<typeof editForm> = {
  display_name: [{ max: 64, message: "姓名或昵称不能超过64个字符", trigger: "blur" }],
  company_name: [{ max: 128, message: "企业名称不能超过128个字符", trigger: "blur" }],
  mobile: [
    {
      validator: (_rule, value: string, callback) => {
        if (!value || /^(?:\+?86)?1[3-9]\d{9}$/.test(value.replace(/\s/g, ""))) callback();
        else callback(new Error("请输入正确的手机号"));
      },
      trigger: "blur",
    },
  ],
  email: [{ type: "email", message: "请输入正确的邮箱地址", trigger: "blur" }],
};
const creditForm = reactive({
  direction: "grant" as "grant" | "deduct",
  amount: 1000,
  expires_in_days: 365,
  reason: "",
});
let creditSubmission: { fingerprint: string; key: string } | null = null;
const segments = computed(() =>
  [
    { label: "全部用户", value: "" },
    { label: "已订阅", value: "subscribed" },
    { label: "未订阅", value: "unsubscribed" },
    { label: "已到期", value: "expired" },
    { label: "低积分", value: "low_credits" },
    { label: "新注册", value: "new" },
    { label: "7天未活跃", value: "inactive_7d" },
    { label: "30天未活跃", value: "inactive_30d" },
    { label: "高频模型用户", value: "high_usage" },
    { label: "有人工标签", value: "tagged" },
  ].filter((item) => !localMode.value || item.value !== "low_credits")
);
const avatarColors = ["#5b8ff9", "#61d9a5", "#f6bd16", "#e8684a", "#9270ca", "#6dc8ec"];
const avatarColor = (row: ClientUserInfo) =>
  avatarColors[
    [...(row.username || "用户")].reduce((sum, char) => sum + char.charCodeAt(0), 0) %
      avatarColors.length
  ];
const allSearchItems = computed<SearchFormItem[]>(() => [
  {
    label: "关键词",
    key: "keyword",
    type: "input",
    placeholder: "账号、姓名、企业或手机号",
    clearable: true,
    span: 6,
  },
  {
    label: "账号状态",
    key: "status",
    type: "select",
    props: {
      placeholder: "请选择状态",
      clearable: true,
      options: [
        { label: "正常", value: "active" },
        { label: "已停用", value: "disabled" },
      ],
    },
    span: 6,
  },
  {
    label: "订阅状态",
    key: "subscription_status",
    type: "select",
    props: {
      placeholder: "请选择订阅状态",
      clearable: true,
      options: [
        { label: "订阅中", value: "active" },
        { label: "已到期", value: "expired" },
      ],
    },
    span: 6,
  },
  {
    label: "套餐",
    key: "catalog_plan_id",
    type: "select",
    props: {
      placeholder: "请选择套餐",
      clearable: true,
      filterable: true,
      options: plans.value.map((plan) => ({ label: plan.name, value: plan.id })),
    },
    span: 6,
  },
  {
    label: "人工标签",
    key: "tag",
    type: "input",
    placeholder: "请输入标签",
    clearable: true,
    expandOnly: true,
    span: 6,
  },
  {
    label: "用户等级",
    key: "usage_grade",
    type: "select",
    props: {
      clearable: true,
      placeholder: "请选择等级",
      options: ["R1", "R2", "R3"].map((value) => ({ label: value, value })),
    },
    expandOnly: true,
    span: 6,
  },
  {
    label: "推广等级",
    key: "promotion_grade",
    type: "select",
    props: {
      clearable: true,
      options: [
        { label: "尚未定级", value: "ungraded" },
        ...["A1", "A2", "A3"].map((value) => ({ label: value, value })),
      ],
    },
    expandOnly: true,
    span: 6,
  },
  {
    label: "最低积分",
    key: "min_credits",
    type: "number",
    props: { min: 0, controls: false, placeholder: "最低积分" },
    expandOnly: true,
    span: 6,
  },
  {
    label: "最高积分",
    key: "max_credits",
    type: "number",
    props: { min: 0, controls: false, placeholder: "最高积分" },
    expandOnly: true,
    span: 6,
  },
  {
    label: "注册时间",
    key: "registered_at",
    type: "datetimerange",
    props: { valueFormat: "YYYY-MM-DD HH:mm:ss" },
    expandOnly: true,
    span: 12,
  },
  {
    label: "最后活跃",
    key: "last_active_at",
    type: "datetimerange",
    props: { valueFormat: "YYYY-MM-DD HH:mm:ss" },
    expandOnly: true,
    span: 12,
  },
]);
const searchItems = computed(() =>
  allSearchItems.value.filter(
    (item) => !localMode.value || !["min_credits", "max_credits"].includes(item.key)
  )
);

function userActions(row: ClientUserInfo): TableOperationAction[] {
  const actions: TableOperationAction[] = [
    { key: "detail", label: "详情", artType: "view", run: () => void openDetail(row) },
    {
      key: "edit",
      label: "编辑",
      artType: "edit",
      perm: "workspace:user:management:update",
      run: () => openEdit(row),
    },
    {
      key: "credits",
      label: "调积分",
      artType: "custom",
      icon: "ri:coins-line",
      perm: "workspace:user:management:credits",
      run: () => openCredit(row),
    },
    {
      key: "duration",
      label: "调天数",
      artType: "custom",
      icon: "ri:calendar-line",
      perm: "workspace:user:management:duration",
      run: () => {
        durationUser.value = row;
        durationVisible.value = true;
      },
    },
    {
      key: "password",
      label: "临时密码",
      artType: "custom",
      icon: "ri:lock-password-line",
      color: "var(--el-color-warning)",
      perm: "workspace:user:management:reset-password",
      run: () => void resetPassword(row),
    },
    {
      key: "status",
      label: row.status === "active" ? "停用" : "启用",
      artType: "custom",
      icon: row.status === "active" ? "ri:forbid-2-line" : "ri:checkbox-circle-line",
      color: row.status === "active" ? "var(--el-color-danger)" : "var(--el-color-success)",
      perm: "workspace:user:management:update",
      run: () => void toggleStatus(row),
    },
  ];
  return actions.filter(
    (action) =>
      (action.key !== "credits" || !localMode.value) &&
      (action.key !== "duration" ||
        localMode.value ||
        currentApp.value?.service_mode === "user_choice")
  );
}

const userTable = useTableColumns<ClientUserInfo>(() => [
  {
    prop: "username",
    label: "用户",
    minWidth: 210,
    formatter: (row: ClientUserInfo) =>
      h("div", { class: "user-cell" }, [
        h(
          ElAvatar,
          {
            src: row.avatar,
            size: 34,
            style: { backgroundColor: avatarColor(row), color: "#fff" },
          },
          () => (row.display_name || row.username).slice(0, 1).toUpperCase()
        ),
        h("span", { class: "user-cell__text" }, [
          h("strong", row.display_name || row.username),
          h("small", row.username),
        ]),
      ]),
  },
  {
    prop: "company_name",
    label: "企业",
    minWidth: 150,
    showOverflowTooltip: true,
    formatter: (row: ClientUserInfo) => row.company_name || "—",
  },
  {
    prop: "mobile",
    label: "手机号",
    minWidth: 130,
    showOverflowTooltip: true,
    formatter: (row: ClientUserInfo) => row.mobile || "—",
  },
  {
    prop: "usage_grade",
    label: "用户等级",
    width: 145,
    formatter: (row: ClientUserInfo) => {
      return h(ElTag, { effect: "light", round: true }, () => row.usage_grade || "R1");
    },
  },
  {
    prop: "promotion_grade",
    label: "推广等级",
    width: 110,
    formatter: (row: ClientUserInfo) =>
      h(ElTag, { type: "success", effect: "plain" }, () =>
        !row.promotion_grade || row.promotion_grade === "ungraded" ? "未定级" : row.promotion_grade
      ),
  },
  {
    prop: "current_subscription",
    label: "当前订阅",
    minWidth: 130,
    formatter: (row: ClientUserInfo) =>
      h(
        ElTag,
        { type: row.subscription_status === "active" ? "success" : "info", effect: "plain" },
        () => row.current_subscription || "未订阅"
      ),
  },
  {
    prop: "subscription_expires_at",
    label: "订阅到期时间",
    minWidth: 180,
    formatter: (row: ClientUserInfo) => row.subscription_expires_at || "未开通",
  },
  {
    prop: "remaining_duration",
    label: "剩余时长",
    width: 115,
    formatter: (row: ClientUserInfo) =>
      remainingSubscriptionTime(row.subscription_expires_at, row.subscription_status),
  },
  {
    prop: "available_credits",
    label: "可用积分",
    width: 110,
    sortable: true,
    formatter: (row: ClientUserInfo) => row.available_credits.toLocaleString(),
  },
  {
    prop: "pending_credits",
    label: "待释放",
    width: 100,
    formatter: (row: ClientUserInfo) => row.pending_credits.toLocaleString(),
  },
  {
    prop: "total_paid_fen",
    label: "累计支付",
    width: 110,
    formatter: (row: ClientUserInfo) => `¥${(row.total_paid_fen / 100).toFixed(2)}`,
  },
  {
    prop: "last_active_at",
    label: "最后活跃",
    width: 168,
    sortable: true,
    formatter: (row: ClientUserInfo) => row.last_active_at || "从未活跃",
  },
  { prop: "registered_at", label: "注册时间", width: 168, sortable: true },
  {
    prop: "status",
    label: "状态",
    width: 88,
    formatter: (row: ClientUserInfo) =>
      h(ElTag, { type: row.status === "active" ? "success" : "danger", effect: "light" }, () =>
        row.status === "active" ? "正常" : "停用"
      ),
  },
  {
    prop: "operation",
    label: "操作",
    width: 140,
    fixed: "right",
    align: "center",
    formatter: (row: ClientUserInfo) =>
      renderTableOperationCell(userActions(row), {
        maxInline: 2,
        wrapperClass: "inline-flex items-center justify-end gap-1",
      }),
  },
]);

const { columnChecks: allColumnChecks, columns: allColumns } = userTable;
// Mode rules apply after saved column preferences, including the column picker.
const columns = computed(() =>
  allColumns.value.filter((column) => billingColumnVisible(column.prop, localMode.value))
);
const columnChecks = computed({
  get: () =>
    allColumnChecks.value.filter((column) => billingColumnVisible(column.prop, localMode.value)),
  set: (value) => {
    allColumnChecks.value = [
      ...value,
      ...allColumnChecks.value.filter(
        (column) => !billingColumnVisible(column.prop, localMode.value)
      ),
    ];
  },
});

const pagination = computed(() => ({
  current: query.page_no || 1,
  size: query.page_size || 10,
  total: total.value,
}));

async function handleSearch(params: Record<string, unknown>) {
  await searchBarRef.value?.validate?.();
  Object.assign(query, params, { page_no: 1 });
  await load();
}

async function handleSizeChange(size: number) {
  query.page_size = size;
  query.page_no = 1;
  await load();
}

async function handleCurrentChange(page: number) {
  query.page_no = page;
  await load();
}
async function load() {
  if (!currentApp.value) return;
  if (localMode.value) {
    query.min_credits = undefined;
    query.max_credits = undefined;
    if (query.segment === "low_credits") query.segment = undefined;
  }
  loading.value = true;
  try {
    const response = await ClientUserAPI.list(query);
    rows.value = response.data.data?.items || [];
    total.value = response.data.data?.total || 0;
  } finally {
    loading.value = false;
  }
}
async function loadPlans() {
  if (!currentApp.value) return;
  const response = await BillingAPI.plans();
  plans.value = response.data.data || [];
}
async function resetFilters() {
  Object.assign(query, {
    page_no: 1,
    keyword: undefined,
    status: undefined,
    segment: undefined,
    subscription_status: undefined,
    catalog_plan_id: undefined,
    min_credits: undefined,
    max_credits: undefined,
    tag: undefined,
    level_code: undefined,
    usage_grade: undefined,
    promotion_grade: undefined,
    segment_id: undefined,
    registered_at: undefined,
    last_active_at: undefined,
  });
  await load();
}
async function selectSegment(value?: string) {
  query.segment = value || undefined;
  query.page_no = 1;
  await load();
}
async function openDetail(value: unknown) {
  const row = value as ClientUserInfo;
  const [detailResult, activityResult] = await Promise.allSettled([
    ClientUserAPI.detail(row.id!),
    ClientUserAPI.activity(row.id!),
  ]);
  selected.value = detailResult.status === "fulfilled" ? detailResult.value.data.data || row : row;
  activity.value =
    activityResult.status === "fulfilled" ? activityResult.value.data.data : undefined;
  detailVisible.value = true;
  if (activityResult.status === "rejected")
    ElMessage.warning("次要用量数据暂时不可用，基本档案已正常打开");
}
async function loadSegments() {
  if (!currentApp.value) return;
  const response = await ClientUserAPI.segments();
  savedSegments.value = response.data.data || [];
}
async function saveSegment() {
  const { value } = await ElMessageBox.prompt("请输入分群名称", "保存当前筛选为动态分群", {
    inputPattern: /\S{2,}/,
    inputErrorMessage: "至少输入2个字符",
  });
  const filters: Record<string, unknown> = {};
  if (query.usage_grade) filters.usage_grade = query.usage_grade;
  if (query.promotion_grade) filters.promotion_grade = query.promotion_grade;
  if (query.status) filters.status = query.status;
  await ClientUserAPI.createSegment({
    name: value,
    description: "由用户管理筛选条件保存",
    filters,
  });
  await loadSegments();
  ElMessage.success("动态分群已保存");
}
async function toggleStatus(value: unknown) {
  const row = value as ClientUserInfo;
  const next = row.status === "active" ? "disabled" : "active";
  const { value: reason } = await ElMessageBox.prompt(
    `请输入${next === "disabled" ? "停用" : "启用"}原因`,
    "账号状态",
    { inputPattern: /\S{2,}/, inputErrorMessage: "至少输入2个字符" }
  );
  await ClientUserAPI.setStatus(row.id!, next, reason);
  await load();
}
async function resetPassword(value: unknown) {
  const row = value as ClientUserInfo;
  await ElMessageBox.confirm("临时密码只会展示一次，生成后用户现有登录立即失效。", "生成临时密码", {
    type: "warning",
  });
  const response = await ClientUserAPI.temporaryPassword(row.id!);
  await ElMessageBox.alert(response.data.data?.temporary_password || "", "临时密码（请安全转交）", {
    confirmButtonText: "我已保存",
  });
}
function openCredit(value: unknown) {
  creditUser.value = value as ClientUserInfo;
  creditSubmission = null;
  Object.assign(creditForm, {
    direction: "grant",
    amount: 1000,
    expires_in_days: 365,
    reason: "",
  });
  creditVisible.value = true;
}
function openEdit(value: unknown) {
  const row = value as ClientUserInfo;
  editUser.value = row;
  Object.assign(editForm, {
    display_name: row.display_name || "",
    company_name: row.company_name || "",
    mobile: row.mobile || "",
    email: row.email || "",
    description: row.description || "",
  });
  editVisible.value = true;
  nextTick(() => editFormRef.value?.clearValidate());
}
async function saveEdit() {
  if (!editUser.value?.id) return;
  await editFormRef.value?.validate();
  editSaving.value = true;
  try {
    await ClientUserAPI.update(editUser.value.id, {
      display_name: editForm.display_name || undefined,
      company_name: editForm.company_name || undefined,
      mobile: editForm.mobile || undefined,
      email: editForm.email || undefined,
      description: editForm.description || undefined,
    });
    editVisible.value = false;
    ElMessage.success("用户资料已更新");
    await load();
  } finally {
    editSaving.value = false;
  }
}
async function saveCredit() {
  if (!creditUser.value?.id || creditSaving.value) return;
  const reason = creditForm.reason.trim();
  if (reason.length < 2) {
    ElMessage.warning("调整原因至少输入2个字符");
    return;
  }
  creditSaving.value = true;
  try {
    const signedAmount = creditForm.direction === "deduct" ? -creditForm.amount : creditForm.amount;
    const fingerprint = JSON.stringify([
      creditUser.value.id,
      signedAmount,
      reason,
      creditForm.expires_in_days,
    ]);
    if (!creditSubmission || creditSubmission.fingerprint !== fingerprint) {
      creditSubmission = { fingerprint, key: crypto.randomUUID().replaceAll("-", "") };
    }
    const response = await ClientUserAPI.adjustCredits(creditUser.value.id, {
      amount: signedAmount,
      reason,
      expires_in_days: creditForm.expires_in_days,
      idempotency_key: creditSubmission.key,
    });
    ElMessage.success(
      `积分已调整，可用余额 ${response.data.data?.available.toLocaleString() || 0}`
    );
    creditVisible.value = false;
    await load();
  } finally {
    creditSaving.value = false;
  }
}
async function addTag() {
  if (!selected.value?.id) return;
  const { value } = await ElMessageBox.prompt("请输入标签名称", "添加人工标签", {
    inputPattern: /\S+/,
    inputErrorMessage: "标签不能为空",
  });
  await ClientUserAPI.addTag(selected.value.id, value);
  await openDetail(selected.value);
}
async function removeTag(tagId: number) {
  if (!selected.value?.id) return;
  await ClientUserAPI.removeTag(selected.value.id, tagId);
  await openDetail(selected.value);
}
watch(
  [() => currentApp.value?.id, localMode],
  () => Promise.all([load(), loadPlans(), loadSegments()]),
  { immediate: true }
);
watch(localMode, () => {
  creditVisible.value = false;
  durationVisible.value = false;
});
watch([creditVisible, editVisible], ([credit, edit]) =>
  clientAppStore.markDirty("client-user-editor", credit || edit)
);
onUnmounted(() => clientAppStore.markDirty("client-user-editor", false));
</script>

<style scoped>
.user-page {
  min-height: 0;
}

.segment-select {
  width: 150px;
}

.saved-segment-select {
  width: 190px;
}

.level-table {
  margin-top: 14px;
}

.level-summary {
  display: grid;
  grid-template-columns: repeat(3, 150px) 1fr;
  gap: 12px;
  align-items: stretch;
  margin-bottom: 16px;
}

.level-summary > div {
  display: grid;
  gap: 2px;
  padding: 12px 14px;
  background: var(--el-color-primary-light-9);
  border: 1px solid var(--el-color-primary-light-7);
  border-radius: 10px;
}

.level-summary strong {
  font-size: 17px;
  color: var(--el-color-primary);
}

.level-summary span,
.level-summary p {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.dimension-name {
  display: grid;
  gap: 2px;
}

.dimension-name small {
  overflow: hidden;
  text-overflow: ellipsis;
  font-size: 11px;
  color: var(--el-text-color-secondary);
  white-space: nowrap;
}

.number-with-unit {
  display: flex;
  gap: 8px;
  align-items: center;
}

.number-with-unit span {
  flex: none;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.level-summary p {
  padding: 10px 14px;
  margin: 0;
  background: var(--el-fill-color-lighter);
  border-radius: 10px;
}

:deep(.user-cell) {
  display: flex;
  gap: 10px;
  align-items: center;
}

:deep(.user-cell__text) {
  display: grid;
  min-width: 0;
  line-height: 1.3;
}

:deep(.user-cell__text strong) {
  overflow: hidden;
  text-overflow: ellipsis;
  color: var(--el-text-color-primary);
}

:deep(.user-cell__text small) {
  color: var(--el-text-color-secondary);
}

.weight-total {
  margin-right: 18px;
  color: var(--el-text-color-secondary);
}

.credit-form {
  margin-top: 16px;
}

.dialog-user {
  margin: 0 0 14px;
  color: var(--el-text-color-secondary);
}

.credit-form :deep(.el-input-number) {
  width: 100%;
}

.edit-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0 14px;
}

.edit-dialog-heading {
  display: flex;
  gap: 12px;
  align-items: center;
}

.edit-dialog-heading > div {
  display: grid;
  gap: 3px;
}

.edit-dialog-heading strong {
  font-size: 16px;
  color: var(--el-text-color-primary);
}

.edit-dialog-heading small,
.form-section__title span {
  font-size: 11px;
  color: var(--el-text-color-secondary);
}

.form-section {
  padding: 16px 0 2px;
  margin-bottom: 4px;
  border-top: 1px solid var(--el-border-color-lighter);
}

.form-section:first-child {
  padding-top: 4px;
  border-top: 0;
}

.form-section--last {
  margin-bottom: 0;
}

.form-section__title {
  display: flex;
  gap: 10px;
  align-items: baseline;
  margin-bottom: 12px;
}

.form-section__title strong {
  font-size: 13px;
  color: var(--el-text-color-primary);
}

:deep(.client-user-edit-dialog .el-dialog__body) {
  max-height: min(62vh, 620px);
  padding-top: 8px;
  overflow: auto;
}

:deep(.client-user-edit-dialog .el-dialog__footer) {
  position: sticky;
  bottom: 0;
  z-index: 2;
  padding-top: 14px;
  background: var(--el-bg-color);
  border-top: 1px solid var(--el-border-color-lighter);
}

:deep(.client-user-edit-dialog .el-form-item__label) {
  font-size: 12px;
  font-weight: 500;
  color: var(--el-text-color-regular);
}

@media (width <= 700px) {
  .edit-grid {
    grid-template-columns: 1fr;
  }
}
</style>
