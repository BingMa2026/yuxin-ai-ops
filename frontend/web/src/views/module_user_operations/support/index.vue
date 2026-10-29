<template>
  <main class="fa-full-height">
    <FaSearchBar
      v-show="showSearchBar"
      :model-value="query"
      :items="searchItems"
      :is-expand="false"
      @update:model-value="Object.assign(query, $event)"
      @search="search"
      @reset="reset"
    />
    <ElCard class="fa-table-card" :style="{ 'margin-top': showSearchBar ? '12px' : '0' }">
      <FaTableHeader
        v-model:columns="columnChecks"
        v-model:showSearchBar="showSearchBar"
        :loading="loading"
        @refresh="load"
      />
      <FaTable
        :loading="loading"
        :data="rows"
        :columns="columns"
        :pagination="pagination"
        @pagination:size-change="changeSize"
        @pagination:current-change="changePage"
      />
    </ElCard>

    <ElDrawer v-model="drawerVisible" title="工单详情" size="min(920px, 96vw)" destroy-on-close>
      <template v-if="detail">
        <div class="ticket-head">
          <div>
            <strong>{{ detail.subject }}</strong
            ><small
              >{{ detail.ticket_no }} ·
              {{ detail.username || detail.display_name || `用户 #${detail.user_id}` }}</small
            >
          </div>
          <ElTag :type="statusType(detail.status)">{{ statusName(detail.status) }}</ElTag>
        </div>
        <ElDescriptions :column="3" border>
          <ElDescriptionsItem label="性质">{{
            detail.kind === "complaint" ? "客诉" : "产品反馈"
          }}</ElDescriptionsItem>
          <ElDescriptionsItem label="分类">{{ categoryName(detail.category) }}</ElDescriptionsItem>
          <ElDescriptionsItem label="SLA截止">{{ detail.sla_due_at }}</ElDescriptionsItem>
          <ElDescriptionsItem label="优先级"
            ><ElSelect v-model="edit.priority" size="small" @change="saveState"
              ><ElOption
                v-for="item in priorityOptions"
                :key="item.value"
                :label="item.label"
                :value="item.value" /></ElSelect
          ></ElDescriptionsItem>
          <ElDescriptionsItem label="状态"
            ><ElSelect v-model="edit.status" size="small" @change="saveState"
              ><ElOption
                v-for="item in statusOptions"
                :key="item.value"
                :label="item.label"
                :value="item.value" /></ElSelect
          ></ElDescriptionsItem>
          <ElDescriptionsItem v-if="detail.kind === 'feedback'" label="反馈价值"
            ><ElSelect
              v-model="edit.value_grade"
              :disabled="detail.adopted"
              placeholder="采纳前选择价值等级"
              ><ElOption
                v-for="grade in ['S', 'A', 'B', 'C']"
                :key="grade"
                :value="grade"
                :label="grade" /></ElSelect
          ></ElDescriptionsItem>
          <ElDescriptionsItem label="反馈采纳"
            ><ElSwitch
              v-model="edit.adopted"
              :disabled="detail.kind !== 'feedback' || !edit.value_grade || detail.adopted"
              @change="saveState"
          /></ElDescriptionsItem>
        </ElDescriptions>
        <section class="conversation">
          <article class="message client">
            <header>用户提交</header>
            <p>{{ detail.content }}</p>
            <AttachmentLinks :items="detail.attachments" />
          </article>
          <article
            v-for="item in detail.messages"
            :key="item.id"
            class="message"
            :class="[item.sender_type, { internal: item.internal }]"
          >
            <header>
              {{
                item.internal ? "内部备注" : item.sender_type === "client" ? "用户补充" : "运营回复"
              }}
              <small>{{ item.created_time }}</small>
            </header>
            <p>{{ item.content }}</p>
            <AttachmentLinks :items="item.attachments" />
          </article>
        </section>
        <div v-if="detail.status !== 'closed'" class="reply-box">
          <ElInput
            v-model="reply.content"
            type="textarea"
            :rows="4"
            placeholder="输入公开回复或内部备注"
          />
          <div>
            <ElCheckbox v-model="reply.internal">仅内部可见</ElCheckbox
            ><ElButton type="primary" :loading="replying" @click="sendReply">发送</ElButton>
          </div>
        </div>
      </template>
    </ElDrawer>
  </main>
</template>

<script setup lang="ts">
import { ElMessage, ElTag } from "element-plus";
import UserOperationsAPI, {
  type SupportTicket,
  type TicketStatus,
} from "@/api/module_user_operations";
import type { SearchFormItem } from "@/components/forms/fa-search-bar/index.vue";
import FaTableHeader from "@/components/tables/fa-table-header/index.vue";
import { renderTableOperationCell } from "@utils";
import AttachmentLinks from "./components/AttachmentLinks.vue";

defineOptions({ name: "SupportTickets" });
const query = reactive({ keyword: "", kind: "", category: "", status: "", priority: "" });
const submitted = ref({ ...query });
const rows = ref<SupportTicket[]>([]);
const total = ref(0);
const pageNo = ref(1);
const pageSize = ref(10);
const loading = ref(false);
const showSearchBar = ref(true);
const drawerVisible = ref(false);
const detail = ref<SupportTicket>();
const replying = ref(false);
const reply = reactive({ content: "", internal: false });
const edit = reactive<{
  status: TicketStatus;
  priority: SupportTicket["priority"];
  adopted: boolean;
  value_grade: "S" | "A" | "B" | "C";
}>({ status: "pending", priority: "normal", adopted: false, value_grade: "C" });
const statusOptions = [
  { label: "待受理", value: "pending" },
  { label: "处理中", value: "processing" },
  { label: "待用户补充", value: "waiting_user" },
  { label: "已解决", value: "resolved" },
  { label: "已关闭", value: "closed" },
] as const;
const priorityOptions = [
  { label: "低（72小时）", value: "low" },
  { label: "普通（48小时）", value: "normal" },
  { label: "高（24小时）", value: "high" },
  { label: "紧急（4小时）", value: "urgent" },
] as const;
const searchItems: SearchFormItem[] = [
  {
    label: "关键词",
    key: "keyword",
    type: "input",
    placeholder: "工单号、标题",
    props: { clearable: true },
    span: 6,
  },
  {
    label: "性质",
    key: "kind",
    type: "select",
    props: {
      clearable: true,
      options: [
        { label: "客诉", value: "complaint" },
        { label: "产品反馈", value: "feedback" },
      ],
    },
    span: 6,
  },
  {
    label: "分类",
    key: "category",
    type: "select",
    props: {
      clearable: true,
      options: [
        { label: "服务投诉", value: "service" },
        { label: "计费退款", value: "billing" },
        { label: "数据安全", value: "security" },
        { label: "程序故障", value: "bug" },
        { label: "功能建议", value: "feature" },
        { label: "体验问题", value: "experience" },
        { label: "AI效果", value: "ai_quality" },
        { label: "其他", value: "other" },
      ],
    },
    span: 6,
  },
  {
    label: "状态",
    key: "status",
    type: "select",
    props: { clearable: true, options: statusOptions },
    span: 6,
  },
  {
    label: "优先级",
    key: "priority",
    type: "select",
    props: { clearable: true, options: priorityOptions },
    span: 6,
  },
];
const statusName = (value: string) =>
  statusOptions.find((item) => item.value === value)?.label || value;
const statusType = (value: string) =>
  value === "resolved"
    ? "success"
    : value === "closed"
      ? "info"
      : value === "pending"
        ? "danger"
        : "warning";
const priorityType = (value: string) =>
  (({ urgent: "danger", high: "warning", normal: "primary", low: "info" })[value] || "info") as
    | "primary"
    | "success"
    | "warning"
    | "info"
    | "danger";
const categoryName = (value: string) =>
  ({
    service: "服务投诉",
    billing: "计费退款",
    security: "数据安全",
    bug: "程序故障",
    feature: "功能建议",
    experience: "体验问题",
    ai_quality: "AI效果",
    other: "其他",
  })[value] || value;
const { columnChecks, columns } = useTableColumns<SupportTicket>(() => [
  { type: "globalIndex", width: 56, label: "序号" },
  { prop: "ticket_no", label: "工单号", minWidth: 165 },
  { prop: "subject", label: "标题", minWidth: 220, showOverflowTooltip: true },
  {
    prop: "username",
    label: "用户",
    minWidth: 130,
    formatter: (row) => row.display_name || row.username || `#${row.user_id}`,
  },
  {
    prop: "kind",
    label: "性质",
    width: 90,
    formatter: (row) =>
      h(ElTag, { type: row.kind === "complaint" ? "danger" : "success", effect: "plain" }, () =>
        row.kind === "complaint" ? "客诉" : "产品反馈"
      ),
  },
  {
    prop: "category",
    label: "分类",
    width: 105,
    formatter: (row) =>
      h(ElTag, { type: "info", effect: "light" }, () => categoryName(row.category)),
  },
  {
    prop: "priority",
    label: "优先级",
    width: 90,
    formatter: (row) =>
      h(
        ElTag,
        { type: priorityType(row.priority), effect: "light" },
        () => priorityOptions.find((item) => item.value === row.priority)?.label.split("（")[0]
      ),
  },
  {
    prop: "status",
    label: "状态",
    width: 105,
    formatter: (row) =>
      h(ElTag, { type: statusType(row.status), effect: "light" }, () => statusName(row.status)),
  },
  { prop: "sla_due_at", label: "SLA截止", width: 170, sortable: true },
  { prop: "created_time", label: "提交时间", width: 170, sortable: true },
  {
    prop: "operation",
    label: "操作",
    width: 88,
    fixed: "right",
    align: "center",
    formatter: (row) =>
      renderTableOperationCell([
        {
          key: "detail",
          label: "处理",
          artType: "view",
          perm: "workspace:user:support:list",
          run: () => void open(row),
        },
      ]),
  },
]);
const pagination = computed(() => ({
  current: pageNo.value,
  size: pageSize.value,
  total: total.value,
}));
async function load() {
  loading.value = true;
  try {
    const params: {
      page_no: number;
      page_size: number;
      keyword?: string;
      kind?: string;
      category?: string;
      status?: string;
      priority?: string;
    } = {
      page_no: pageNo.value,
      page_size: pageSize.value,
    };
    if (submitted.value.keyword) params.keyword = submitted.value.keyword;
    if (submitted.value.kind) params.kind = submitted.value.kind;
    if (submitted.value.category) params.category = submitted.value.category;
    if (submitted.value.status) params.status = submitted.value.status;
    if (submitted.value.priority) params.priority = submitted.value.priority;
    const res = await UserOperationsAPI.tickets({
      ...params,
    });
    rows.value = res.data.data?.items || [];
    total.value = res.data.data?.total || 0;
  } finally {
    loading.value = false;
  }
}
function search(value: Record<string, unknown>) {
  submitted.value = {
    keyword: String(value.keyword || ""),
    kind: String(value.kind || ""),
    category: String(value.category || ""),
    status: String(value.status || ""),
    priority: String(value.priority || ""),
  };
  pageNo.value = 1;
  void load();
}
function reset() {
  Object.assign(query, { keyword: "", kind: "", category: "", status: "", priority: "" });
  submitted.value = { ...query };
  pageNo.value = 1;
  void load();
}
function changeSize(value: number) {
  pageSize.value = value;
  pageNo.value = 1;
  void load();
}
function changePage(value: number) {
  pageNo.value = value;
  void load();
}
async function open(row: SupportTicket) {
  const res = await UserOperationsAPI.ticket(Number(row.id));
  detail.value = res.data.data;
  if (detail.value)
    Object.assign(edit, {
      status: detail.value.status,
      priority: detail.value.priority,
      adopted: detail.value.adopted,
      value_grade: detail.value.value_grade || "C",
    });
  drawerVisible.value = true;
}
async function saveState() {
  if (!detail.value?.id) return;
  const res = await UserOperationsAPI.updateTicket(detail.value.id, edit);
  detail.value = res.data.data;
  ElMessage.success("工单已更新");
  await load();
}
async function sendReply() {
  if (!detail.value?.id || !reply.content.trim()) return ElMessage.warning("请输入回复内容");
  replying.value = true;
  try {
    await UserOperationsAPI.replyTicket(detail.value.id, { ...reply });
    reply.content = "";
    await open(detail.value);
  } finally {
    replying.value = false;
  }
}
onMounted(load);
</script>

<style scoped>
.ticket-head,
.reply-box > div {
  display: flex;
  gap: 12px;
  align-items: center;
  justify-content: space-between;
}

.ticket-head {
  margin-bottom: 16px;
}

.ticket-head div {
  display: grid;
  gap: 4px;
}

.ticket-head small,
.message header small {
  font-weight: 400;
  color: var(--el-text-color-secondary);
}

.conversation {
  display: grid;
  gap: 12px;
  margin: 18px 0;
}

.message {
  padding: 14px;
  background: var(--el-fill-color-extra-light);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 10px;
}

.message.staff {
  margin-left: 8%;
}

.message.client {
  margin-right: 8%;
}

.message.internal {
  background: var(--el-color-warning-light-9);
  border-style: dashed;
}

.message header {
  font-weight: 600;
}

.message p {
  margin: 8px 0;
  white-space: pre-wrap;
}

.reply-box {
  display: grid;
  gap: 10px;
  padding-top: 16px;
  border-top: 1px solid var(--el-border-color-lighter);
}
</style>
