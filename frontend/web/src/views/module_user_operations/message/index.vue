<template>
  <main class="fa-full-height">
    <FaSearchBar
      v-show="showSearchBar && activeTab !== 'delivery'"
      :model-value="filters"
      :items="searchItems"
      :show-expand="false"
      :is-expand="false"
      @update:model-value="Object.assign(filters, $event)"
      @search="applyFilters"
      @reset="resetFilters"
    />
    <ElCard class="fa-table-card" :style="{ 'margin-top': showSearchBar ? '12px' : '0' }">
      <ElTabs v-model="activeTab">
        <ElTabPane label="投递记录" name="delivery" lazy>
          <MessageDeliveries v-if="activeTab === 'delivery'" />
        </ElTabPane>
        <ElTabPane label="触达任务" name="campaign">
          <FaTableHeader
            v-model:columns="campaignChecks"
            v-model:showSearchBar="showSearchBar"
            :loading="loading"
            @refresh="load"
            ><template #left
              ><ElButton
                v-hasPerm="['workspace:user:message:create']"
                type="primary"
                @click="openCampaign"
                ><FaSvgIcon icon="ri:add-line" />新建触达</ElButton
              ></template
            ></FaTableHeader
          >
          <FaTable :loading="loading" :data="filteredCampaigns" :columns="campaignColumns" />
        </ElTabPane>
        <ElTabPane label="消息模板" name="template">
          <FaTableHeader
            v-model:columns="templateChecks"
            v-model:showSearchBar="showSearchBar"
            :loading="loading"
            @refresh="load"
            ><template #left
              ><ElButton
                v-hasPerm="['workspace:user:message:create']"
                type="primary"
                @click="() => openTemplate()"
                ><FaSvgIcon icon="ri:add-line" />新建模板</ElButton
              ></template
            ></FaTableHeader
          >
          <FaTable :loading="loading" :data="filteredTemplates" :columns="templateColumns" />
        </ElTabPane>
      </ElTabs>
    </ElCard>

    <ElDialog
      v-model="templateVisible"
      :title="templateForm.id ? '编辑消息模板' : '新建消息模板'"
      width="min(620px, 94vw)"
      destroy-on-close
    >
      <ElForm label-position="top">
        <ElFormItem label="模板名称"><ElInput v-model="templateForm.name" /></ElFormItem>
        <ElFormItem label="消息标题"><ElInput v-model="templateForm.title" /></ElFormItem>
        <ElFormItem label="消息正文">
          <FaWangEditor v-model="templateForm.content" height="220px" mode="simple" />
        </ElFormItem>
        <ElFormItem label="状态">
          <ElRadioGroup v-model="templateForm.status">
            <ElRadio value="active">启用</ElRadio>
            <ElRadio value="inactive">停用</ElRadio>
          </ElRadioGroup>
        </ElFormItem>
      </ElForm>
      <template #footer>
        <ElButton @click="templateVisible = false">取消</ElButton>
        <ElButton type="primary" :loading="saving" @click="saveTemplate">保存</ElButton>
      </template>
    </ElDialog>

    <ElDialog
      v-model="campaignVisible"
      class="campaign-dialog"
      title="新建站内消息触达"
      top="4vh"
      width="min(720px, 95vw)"
      destroy-on-close
    >
      <ElForm label-position="top">
        <div class="form-grid">
          <ElFormItem label="任务名称"><ElInput v-model="campaignForm.name" /></ElFormItem
          ><ElFormItem label="套用模板"
            ><ElSelect v-model="campaignForm.template_id" clearable @change="applyTemplate"
              ><ElOption
                v-for="item in templates.filter((x) => x.status === 'active')"
                :key="item.id"
                :label="item.name"
                :value="item.id || 0" /></ElSelect
          ></ElFormItem>
        </div>
        <ElFormItem label="消息标题"><ElInput v-model="campaignForm.title" /></ElFormItem
        ><ElFormItem label="消息正文"
          ><FaWangEditor v-model="campaignForm.content" height="180px" mode="simple"
        /></ElFormItem>
        <div class="form-grid">
          <ElFormItem label="发送对象"
            ><ElSelect v-model="campaignForm.audience_type"
              ><ElOption label="全部用户" value="all" /><ElOption
                label="新用户"
                value="new" /><ElOption label="LV等级" value="level" /><ElOption
                label="动态分群"
                value="segment" /><ElOption label="指定用户" value="users" /></ElSelect></ElFormItem
          ><ElFormItem v-if="campaignForm.audience_type === 'level'" label="用户等级"
            ><ElSelect v-model="levelCodes" multiple
              ><ElOption
                v-for="level in levels"
                :key="level"
                :label="level"
                :value="level" /></ElSelect></ElFormItem
          ><ElFormItem v-if="campaignForm.audience_type === 'segment'" label="动态分群"
            ><ElSelect v-model="segmentId"
              ><ElOption
                v-for="item in segments"
                :key="item.id"
                :label="`${item.name}（${item.matched_count}人）`"
                :value="item.id || 0" /></ElSelect></ElFormItem
          ><ElFormItem v-if="campaignForm.audience_type === 'users'" label="指定用户"
            ><ElSelect v-model="userIds" multiple filterable
              ><ElOption
                v-for="item in users"
                :key="item.id"
                :label="item.display_name || item.username"
                :value="item.id || 0" /></ElSelect
          ></ElFormItem>
        </div>
        <section class="delivery-panel">
          <div class="delivery-head">
            <strong>发送设置</strong><ElTag type="primary" effect="plain">站内消息</ElTag>
          </div>
          <ElFormItem label="执行方式">
            <ElRadioGroup v-model="sendMode">
              <ElRadioButton value="now">立即发送</ElRadioButton>
              <ElRadioButton value="scheduled">定时发送</ElRadioButton>
              <ElRadioButton value="draft">保存草稿</ElRadioButton>
            </ElRadioGroup>
          </ElFormItem>
          <div v-if="sendMode === 'scheduled'" class="schedule-grid">
            <ElFormItem label="计划发送时间">
              <ElDatePicker
                v-model="campaignForm.scheduled_at"
                type="datetime"
                value-format="YYYY-MM-DDTHH:mm:ssZ"
                :disabled-date="disablePastDate"
                placeholder="选择未来时间"
              />
            </ElFormItem>
            <ElFormItem label="业务时区">
              <ElSelect v-model="campaignForm.timezone">
                <ElOption label="中国标准时间（UTC+8）" value="Asia/Shanghai" />
              </ElSelect>
            </ElFormItem>
          </div>
          <div class="audience-preview">
            <span>预计触达</span
            ><strong>{{ audiencePreview.target_count.toLocaleString() }} 人</strong>
            <small v-if="audiencePreview.sample_users.length"
              >抽样：{{
                audiencePreview.sample_users
                  .map((item) => `${item.name} ${item.level_code}`)
                  .join("、")
              }}</small
            ><small v-else>收件人会在发送时重新计算并冻结快照</small>
            <ElButton link type="primary" :loading="previewing" @click="loadAudiencePreview"
              >重新计算</ElButton
            >
          </div>
        </section>
      </ElForm>
      <template #footer>
        <ElButton @click="campaignVisible = false">取消</ElButton>
        <ElButton type="primary" :loading="saving" @click="saveCampaign">保存</ElButton>
      </template>
    </ElDialog>
  </main>
</template>

<script setup lang="ts">
import MessageDeliveries from "./MessageDeliveries.vue";
import DOMPurify from "dompurify";
import { ElMessage, ElMessageBox, ElTag } from "element-plus";
import ClientUserAPI, { type ClientUserInfo, type UserSegment } from "@/api/module_client/user";
import UserOperationsAPI, {
  type MessageCampaign,
  type MessageTemplate,
} from "@/api/module_user_operations";
import FaTableHeader from "@/components/tables/fa-table-header/index.vue";
import type { SearchFormItem } from "@/components/forms/fa-search-bar/index.vue";
import { renderTableOperationCell } from "@utils";
defineOptions({ name: "MessageTrigger" });
const activeTab = ref("campaign"),
  showSearchBar = ref(true),
  loading = ref(false),
  saving = ref(false);
const previewing = ref(false);
const filters = reactive({ keyword: "", status: "", audience_type: "" });
const appliedFilters = ref({ ...filters });
const templates = ref<MessageTemplate[]>([]),
  campaigns = ref<MessageCampaign[]>([]),
  segments = ref<UserSegment[]>([]),
  users = ref<ClientUserInfo[]>([]);
const templateVisible = ref(false),
  campaignVisible = ref(false),
  sendMode = ref<"now" | "scheduled" | "draft">("now"),
  levelCodes = ref<string[]>([]),
  segmentId = ref<number>(),
  userIds = ref<number[]>([]);
const levels = ["LV1", "LV2", "LV3", "LV4", "LV5"];
const audiencePreview = reactive({
  target_count: 0,
  sample_users: [] as { id: number; name: string; level_code: string }[],
});
const templateForm = reactive({
  id: 0,
  name: "",
  title: "",
  content: "",
  status: "active" as "active" | "inactive",
  content_type: "rich_text" as const,
});
const campaignForm = reactive({
  name: "",
  template_id: undefined as number | undefined,
  title: "",
  content: "",
  audience_type: "all" as MessageCampaign["audience_type"],
  scheduled_at: undefined as string | undefined,
  timezone: "Asia/Shanghai",
  content_type: "rich_text" as const,
});
const searchItems = computed<SearchFormItem[]>(() => [
  {
    label: "关键词",
    key: "keyword",
    type: "input",
    placeholder: activeTab.value === "campaign" ? "任务名称或标题" : "模板名称或标题",
    props: { clearable: true },
    span: 8,
  },
  {
    label: "状态",
    key: "status",
    type: "select",
    props: {
      clearable: true,
      options:
        activeTab.value === "campaign"
          ? [
              { label: "草稿", value: "draft" },
              { label: "待发送", value: "scheduled" },
              { label: "发送中", value: "sending" },
              { label: "已发送", value: "sent" },
              { label: "已取消", value: "cancelled" },
              { label: "失败", value: "failed" },
            ]
          : [
              { label: "启用", value: "active" },
              { label: "停用", value: "inactive" },
            ],
    },
    span: 8,
  },
  ...(activeTab.value === "campaign"
    ? [
        {
          label: "发送对象",
          key: "audience_type",
          type: "select" as const,
          props: {
            clearable: true,
            options: [
              { label: "全部用户", value: "all" },
              { label: "新用户", value: "new" },
              { label: "LV等级", value: "level" },
              { label: "动态分群", value: "segment" },
              { label: "指定用户", value: "users" },
            ],
          },
          span: 8,
        },
      ]
    : []),
]);
const textPreview = (value: string) => DOMPurify.sanitize(value, { ALLOWED_TAGS: [] });
const campaignStatusType = (status: string) =>
  (({
    draft: "info",
    scheduled: "warning",
    sending: "primary",
    sent: "success",
    cancelled: "info",
    failed: "danger",
  })[status] || "info") as "primary" | "success" | "warning" | "info" | "danger";
const statusName = (value: string) =>
  ({
    draft: "草稿",
    scheduled: "待发送",
    sending: "发送中",
    sent: "已发送",
    cancelled: "已取消",
    failed: "失败",
    active: "启用",
    inactive: "停用",
  })[value] || value;
const audienceName = (value: string) =>
  ({ all: "全部用户", new: "新用户", level: "LV等级", segment: "动态分群", users: "指定用户" })[
    value
  ] || value;
const { columnChecks: campaignChecks, columns: campaignColumns } = useTableColumns<MessageCampaign>(
  () => [
    { type: "globalIndex", width: 56, label: "序号" },
    { prop: "name", label: "任务名称", minWidth: 150 },
    { prop: "title", label: "消息标题", minWidth: 200, showOverflowTooltip: true },
    {
      prop: "audience_type",
      label: "发送对象",
      width: 110,
      formatter: (r) =>
        h(ElTag, { type: "primary", effect: "plain" }, () => audienceName(r.audience_type)),
    },
    { prop: "scheduled_at", label: "计划发送", width: 170 },
    { prop: "target_count", label: "目标人数", width: 95 },
    { prop: "delivered_count", label: "已送达", width: 85 },
    { prop: "read_count", label: "已读", width: 75 },
    {
      prop: "status",
      label: "状态",
      width: 90,
      formatter: (r) =>
        h(ElTag, { type: campaignStatusType(r.status), effect: "light" }, () =>
          statusName(r.status)
        ),
    },
    {
      prop: "operation",
      label: "操作",
      width: 90,
      fixed: "right",
      align: "center",
      formatter: (r) =>
        renderTableOperationCell(
          r.status === "draft" || r.status === "scheduled"
            ? [
                {
                  key: "cancel",
                  label: "取消",
                  artType: "custom",
                  icon: "ri:close-circle-line",
                  iconColor: "var(--el-color-danger)",
                  perm: "workspace:user:message:create",
                  run: () => void cancel(r),
                },
              ]
            : []
        ),
    },
  ]
);
const { columnChecks: templateChecks, columns: templateColumns } = useTableColumns<MessageTemplate>(
  () => [
    { type: "globalIndex", width: 56, label: "序号" },
    { prop: "name", label: "模板名称", minWidth: 160 },
    { prop: "title", label: "消息标题", minWidth: 200 },
    {
      prop: "content",
      label: "消息正文",
      minWidth: 260,
      showOverflowTooltip: true,
      formatter: (r) => textPreview(r.content),
    },
    {
      prop: "status",
      label: "状态",
      width: 90,
      formatter: (r) =>
        h(ElTag, { type: r.status === "active" ? "success" : "info", effect: "light" }, () =>
          statusName(r.status)
        ),
    },
    { prop: "updated_time", label: "更新时间", width: 170 },
    {
      prop: "operation",
      label: "操作",
      width: 90,
      fixed: "right",
      align: "center",
      formatter: (r) =>
        renderTableOperationCell([
          {
            key: "edit",
            label: "编辑",
            artType: "edit",
            perm: "workspace:user:message:create",
            run: () => openTemplate(r),
          },
        ]),
    },
  ]
);
async function load() {
  loading.value = true;
  try {
    const [t, c, s, u] = await Promise.all([
      UserOperationsAPI.templates(),
      UserOperationsAPI.campaigns(),
      ClientUserAPI.segments(),
      ClientUserAPI.list({ page_no: 1, page_size: 100 }),
    ]);
    templates.value = t.data.data || [];
    campaigns.value = c.data.data || [];
    segments.value = s.data.data || [];
    users.value = u.data.data?.items || [];
  } finally {
    loading.value = false;
  }
}
function openTemplate(item?: MessageTemplate) {
  Object.assign(
    templateForm,
    item
      ? {
          id: item.id || 0,
          name: item.name,
          title: item.title,
          content: item.content,
          status: item.status,
          content_type: item.content_type,
        }
      : {
          id: 0,
          name: "",
          title: "",
          content: "",
          status: "active",
          content_type: "rich_text",
        }
  );
  templateVisible.value = true;
}
async function saveTemplate() {
  if (!templateForm.name || !templateForm.title || !templateForm.content)
    return ElMessage.warning("请完整填写模板");
  saving.value = true;
  try {
    const data = {
      name: templateForm.name,
      title: templateForm.title,
      content: templateForm.content,
      status: templateForm.status,
      content_type: "rich_text" as const,
    };
    if (templateForm.id) await UserOperationsAPI.updateTemplate(templateForm.id, data);
    else await UserOperationsAPI.createTemplate(data);
    templateVisible.value = false;
    await load();
  } finally {
    saving.value = false;
  }
}
function openCampaign() {
  Object.assign(campaignForm, {
    name: "",
    template_id: undefined,
    title: "",
    content: "",
    audience_type: "all",
    scheduled_at: undefined,
    timezone: "Asia/Shanghai",
    content_type: "rich_text",
  });
  levelCodes.value = [];
  segmentId.value = undefined;
  userIds.value = [];
  sendMode.value = "now";
  campaignVisible.value = true;
  void loadAudiencePreview();
}
function applyTemplate(id: number) {
  const item = templates.value.find((x) => x.id === id);
  if (item) Object.assign(campaignForm, { title: item.title, content: item.content });
}
async function saveCampaign() {
  if (!campaignForm.name || !campaignForm.title || !campaignForm.content)
    return ElMessage.warning("请完整填写触达任务");
  let audience_value: Record<string, unknown> = {};
  if (campaignForm.audience_type === "level") audience_value = { level_codes: levelCodes.value };
  if (campaignForm.audience_type === "segment") audience_value = { segment_id: segmentId.value };
  if (campaignForm.audience_type === "users") audience_value = { user_ids: userIds.value };
  saving.value = true;
  try {
    await UserOperationsAPI.createCampaign({
      ...campaignForm,
      audience_value,
      send_now: sendMode.value === "now",
      scheduled_at: sendMode.value === "scheduled" ? campaignForm.scheduled_at : undefined,
      timezone: campaignForm.timezone,
      content_type: "rich_text",
    });
    campaignVisible.value = false;
    await load();
  } finally {
    saving.value = false;
  }
}
function audienceValue(): Record<string, unknown> {
  if (campaignForm.audience_type === "level") return { level_codes: levelCodes.value };
  if (campaignForm.audience_type === "segment") return { segment_id: segmentId.value };
  if (campaignForm.audience_type === "users") return { user_ids: userIds.value };
  return {};
}
async function loadAudiencePreview() {
  previewing.value = true;
  try {
    const response = await UserOperationsAPI.previewAudience({
      audience_type: campaignForm.audience_type,
      audience_value: audienceValue(),
    });
    Object.assign(audiencePreview, response.data.data || { target_count: 0, sample_users: [] });
  } catch {
    Object.assign(audiencePreview, { target_count: 0, sample_users: [] });
  } finally {
    previewing.value = false;
  }
}
function disablePastDate(date: Date) {
  return date.getTime() < Date.now() - 24 * 60 * 60 * 1000;
}
function applyFilters(values: Record<string, unknown>) {
  appliedFilters.value = {
    keyword: String(values.keyword || ""),
    status: String(values.status || ""),
    audience_type: String(values.audience_type || ""),
  };
}
function resetFilters() {
  Object.assign(filters, { keyword: "", status: "", audience_type: "" });
  appliedFilters.value = { ...filters };
}
const filteredCampaigns = computed(() =>
  campaigns.value.filter((item) => {
    const keyword = appliedFilters.value.keyword.toLowerCase();
    return (
      (!keyword || `${item.name} ${item.title}`.toLowerCase().includes(keyword)) &&
      (!appliedFilters.value.status || item.status === appliedFilters.value.status) &&
      (!appliedFilters.value.audience_type ||
        item.audience_type === appliedFilters.value.audience_type)
    );
  })
);
const filteredTemplates = computed(() =>
  templates.value.filter((item) => {
    const keyword = appliedFilters.value.keyword.toLowerCase();
    return (
      (!keyword || `${item.name} ${item.title}`.toLowerCase().includes(keyword)) &&
      (!appliedFilters.value.status || item.status === appliedFilters.value.status)
    );
  })
);
async function cancel(item: MessageCampaign) {
  await ElMessageBox.confirm("确认取消该触达任务？", "取消任务", { type: "warning" });
  await UserOperationsAPI.cancelCampaign(Number(item.id));
  await load();
}
onMounted(load);
watch(
  [() => campaignForm.audience_type, levelCodes, segmentId, userIds],
  () => {
    if (campaignVisible.value) void loadAudiencePreview();
  },
  { deep: true }
);
watch(activeTab, resetFilters);
</script>
<style scoped>
.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0 14px;
}

.el-select {
  width: 100%;
}

.el-date-editor {
  width: 100%;
}

.delivery-panel {
  padding: 14px 16px 4px;
  background: var(--el-fill-color-extra-light);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 12px;
}

.delivery-head,
.audience-preview {
  display: flex;
  gap: 10px;
  align-items: center;
}

.delivery-head {
  justify-content: space-between;
  margin-bottom: 12px;
}

.schedule-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
}

.audience-preview {
  padding: 11px 12px;
  margin-bottom: 12px;
  background: var(--el-bg-color);
  border-radius: 9px;
}

.audience-preview strong {
  color: var(--el-color-primary);
}

.audience-preview small {
  flex: 1;
  color: var(--el-text-color-secondary);
}

:deep(.campaign-dialog .el-dialog__body) {
  max-height: calc(92vh - 132px);
  overflow-y: auto;
}

@media (width<=700px) {
  .form-grid {
    grid-template-columns: 1fr;
  }

  .schedule-grid {
    grid-template-columns: 1fr;
  }
}
</style>
