<script setup lang="ts">
import { computed, h, onMounted, reactive, ref, watch } from "vue";
import { ElTag } from "element-plus";
import { storeToRefs } from "pinia";
import { useClientAppStore } from "@stores";
import API, { type MessageDelivery } from "@/api/module_user_operations";
import type { SearchFormItem } from "@/components/forms/fa-search-bar/index.vue";
import FaTableHeader from "@/components/tables/fa-table-header/index.vue";

const { currentApp } = storeToRefs(useClientAppStore());
const rows = ref<MessageDelivery[]>([]),
  loading = ref(false),
  failed = ref(false),
  showSearch = ref(true);
const query = reactive({ keyword: "", message_type: "", read_status: "" });
const filters = ref({ ...query });
const pagination = reactive({ current: 1, size: 20, total: 0 });
let generation = 0;
const names: Record<string, string> = {
  credit_grant: "积分到账",
  campaign: "运营触达",
  ticket_reply: "工单回复",
};
const items = computed<SearchFormItem[]>(() => [
  {
    key: "keyword",
    label: "搜索",
    type: "input",
    placeholder: "用户名 / 昵称 / 消息标题",
    span: 6,
  },
  {
    key: "message_type",
    label: "消息类型",
    type: "select",
    span: 6,
    props: {
      clearable: true,
      options: Object.entries(names).map(([value, label]) => ({ value, label })),
    },
  },
  {
    key: "read_status",
    label: "阅读状态",
    type: "select",
    span: 6,
    props: {
      clearable: true,
      options: [
        { label: "未读", value: "unread" },
        { label: "已读", value: "read" },
      ],
    },
  },
]);
const dateTime = (value?: string) =>
  value ? new Date(value).toLocaleString("zh-CN", { hour12: false }) : "—";
const { columns, columnChecks } = useTableColumns<MessageDelivery>(() => [
  { prop: "id", label: "消息编号", width: 95 },
  {
    prop: "display_name",
    label: "收件用户",
    minWidth: 150,
    formatter: (r) => `${r.display_name || r.username} (#${r.user_id})`,
    showOverflowTooltip: true,
  },
  {
    prop: "message_type",
    label: "类型",
    width: 100,
    formatter: (r) => names[r.message_type] || r.message_type,
  },
  { prop: "title", label: "消息标题", minWidth: 160, showOverflowTooltip: true },
  {
    prop: "content",
    label: "消息内容",
    minWidth: 280,
    showOverflowTooltip: true,
    formatter: (r) => (r.content_type === "rich_text" ? "富文本运营消息" : r.content),
  },
  {
    prop: "resource_id",
    label: "关联业务编号",
    minWidth: 120,
    formatter: (r) => r.resource_id || (r.campaign_id ? `任务 #${r.campaign_id}` : "—"),
  },
  {
    prop: "status",
    label: "阅读状态",
    width: 100,
    formatter: (r) =>
      h(ElTag, { type: r.read_at ? "success" : "info", effect: "light" }, () =>
        r.read_at ? "已读" : "未读"
      ),
  },
  {
    prop: "delivered_at",
    label: "送达时间",
    width: 180,
    formatter: (r) => dateTime(r.delivered_at),
  },
  { prop: "read_at", label: "阅读时间", width: 180, formatter: (r) => dateTime(r.read_at) },
]);
async function load() {
  const stamp = ++generation;
  loading.value = true;
  failed.value = false;
  try {
    const result = (
      await API.deliveries({
        page_no: pagination.current,
        page_size: pagination.size,
        keyword: filters.value.keyword || undefined,
        message_type: filters.value.message_type || undefined,
        read_status: filters.value.read_status || undefined,
      })
    ).data.data;
    if (stamp !== generation) return;
    rows.value = result?.items || [];
    pagination.total = result?.total || 0;
  } catch {
    if (stamp === generation) {
      rows.value = [];
      pagination.total = 0;
      failed.value = true;
    }
  } finally {
    if (stamp === generation) loading.value = false;
  }
}
function search() {
  filters.value = { ...query };
  pagination.current = 1;
  void load();
}
function reset() {
  Object.assign(query, { keyword: "", message_type: "", read_status: "" });
  search();
}
function changePage(value: number) {
  pagination.current = value;
  void load();
}
function changeSize(value: number) {
  pagination.size = value;
  pagination.current = 1;
  void load();
}
watch(
  () => currentApp.value?.id,
  () => {
    rows.value = [];
    reset();
  }
);
onMounted(load);
</script>
<template>
  <FaSearchBar
    v-show="showSearch"
    :model-value="query"
    :items="items"
    :show-expand="false"
    @update:model-value="Object.assign(query, $event)"
    @search="search"
    @reset="reset"
  />
  <FaTableHeader
    v-model:columns="columnChecks"
    v-model:showSearchBar="showSearch"
    :loading="loading"
    @refresh="load"
  />
  <ElAlert v-if="failed" title="投递记录加载失败，请重试" type="error" :closable="false" />
  <FaTable
    :loading="loading"
    :data="rows"
    :columns="columns"
    :pagination="pagination"
    @pagination:current-change="changePage"
    @pagination:size-change="changeSize"
  />
</template>
