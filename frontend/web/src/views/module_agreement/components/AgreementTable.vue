<script setup lang="ts">
import { ref, watch } from "vue";
import { ElMessageBox } from "element-plus";
import { resolveStatusColumns, renderTableOperationCell } from "@utils";
import API, { type Agreement } from "@/api/module_agreement";
import FinanceSearchBar from "@/views/module_finance/components/FinanceSearchBar.vue";
import FaTableHeader from "@/components/tables/fa-table-header/index.vue";
import { useAgreementList } from "../use-agreement-list";
import AgreementEditor from "./AgreementEditor.vue";

const {
  currentApp,
  rows,
  query,
  loading,
  failed,
  pagination,
  showSearchBar,
  load,
  search,
  reset,
  changePage,
  changeSize,
} = useAgreementList(API.list);
const editor = ref(false),
  selectedId = ref<number>(),
  readOnly = ref(false),
  busy = ref(false);
const items = [
  {
    label: "协议名称",
    key: "keyword",
    type: "input" as const,
    props: { placeholder: "搜索名称或标识", clearable: true },
  },
  {
    label: "发布状态",
    key: "status",
    type: "select" as const,
    props: {
      clearable: true,
      options: [
        { label: "尚未发布", value: "draft" },
        { label: "已发布", value: "published" },
        { label: "已归档", value: "archived" },
      ],
    },
  },
  {
    label: "草稿状态",
    key: "has_draft",
    type: "select" as const,
    props: {
      clearable: true,
      options: [
        { label: "有草稿", value: "true" },
        { label: "无草稿", value: "false" },
      ],
    },
  },
];
function open(row?: Agreement, view = false) {
  selectedId.value = row?.id;
  readOnly.value = view;
  editor.value = true;
}
async function action(row: Agreement, kind: "archive" | "remove" | "unarchive") {
  if (busy.value) return;
  const app = currentApp.value?.id;
  const label = { archive: "归档", remove: "删除", unarchive: "恢复为草稿" }[kind];
  const confirmed = await ElMessageBox.confirm(
    `将${label}「${currentApp.value?.name}」的《${row.title}》${kind === "archive" ? "，归档后客户端无法读取，历史版本保留" : ""}。`,
    `${label}协议`,
    { type: "warning", confirmButtonText: label, cancelButtonText: "取消" }
  )
    .then(() => true)
    .catch(() => false);
  if (!confirmed || app !== currentApp.value?.id) return;
  busy.value = true;
  try {
    await API[kind](row.id, row.revision);
    if (app === currentApp.value?.id) await load();
  } catch {
    /* Request layer reports errors. */
  } finally {
    busy.value = false;
  }
}
const { columns, columnChecks } = useTableColumns<Agreement>(
  resolveStatusColumns<Agreement>(() => [
    { prop: "title", label: "协议名称", minWidth: 150, showOverflowTooltip: true },
    { prop: "code", label: "协议标识", minWidth: 150, showOverflowTooltip: true },
    {
      prop: "current_version",
      label: "当前生效版本",
      width: 125,
      formatter: (r) => (r.status === "published" ? `V${r.current_version}` : "—"),
    },
    {
      prop: "status",
      label: "发布状态",
      width: 100,
      status: {
        draft: { type: "info", text: "尚未发布" },
        published: { type: "success", text: "已发布" },
        archived: { type: "info", text: "已归档" },
      },
    },
    {
      prop: "has_draft",
      label: "草稿状态",
      width: 120,
      formatter: (r) => (r.has_draft ? "有未发布草稿" : "—"),
    },
    { prop: "updated_time", label: "更新时间", minWidth: 170 },
    {
      prop: "operation",
      label: "操作",
      width: 140,
      fixed: "right",
      formatter: (r) =>
        renderTableOperationCell([
          {
            key: "detail",
            label: "查看",
            artType: "custom",
            icon: "ri:file-text-line",
            run: () => open(r, true),
          },
          ...(r.status !== "archived"
            ? [
                {
                  key: "edit",
                  label: "编辑",
                  artType: "custom" as const,
                  icon: "ri:edit-line",
                  perm: "workspace:user:agreement:update",
                  run: () => open(r),
                },
              ]
            : []),
          {
            key: "state",
            label: r.status === "archived" ? "恢复" : r.current_version ? "归档" : "删除",
            artType: "custom",
            icon: r.current_version ? "ri:archive-line" : "ri:delete-bin-line",
            perm: `workspace:user:agreement:${r.status === "archived" ? "update" : r.current_version ? "publish" : "delete"}`,
            run: () =>
              void action(
                r,
                r.status === "archived" ? "unarchive" : r.current_version ? "archive" : "remove"
              ),
          },
        ]),
    },
  ])
);
watch(
  () => currentApp.value?.id,
  () => {
    editor.value = false;
    selectedId.value = undefined;
  }
);
</script>
<template>
  <section class="fa-full-height">
    <template v-if="currentApp">
      <FinanceSearchBar
        v-show="showSearchBar"
        v-model="query"
        :items="items"
        :is-expand="false"
        :show-expand="true"
        @search="search"
        @reset="reset"
      />
      <ElCard class="fa-table-card" :style="{ marginTop: showSearchBar ? '12px' : '0' }">
        <FaTableHeader
          v-model:columns="columnChecks"
          v-model:showSearchBar="showSearchBar"
          :loading="loading"
          @refresh="load"
          ><template #left
            ><ElButton
              v-hasPerm="['workspace:user:agreement:update']"
              type="primary"
              @click="open()"
              ><FaSvgIcon icon="ri:add-line" />新增协议</ElButton
            ></template
          ></FaTableHeader
        >
        <ElAlert v-if="failed" title="协议加载失败，请刷新重试" type="error" :closable="false" />
        <FaTable
          :loading="loading"
          :data="rows"
          :columns="columns"
          :pagination="pagination"
          @pagination:current-change="changePage"
          @pagination:size-change="changeSize"
        />
      </ElCard>
    </template>
    <ElCard v-else class="fa-table-card"><ElEmpty description="请先选择客户端" /></ElCard>
    <AgreementEditor
      v-if="editor && currentApp?.id"
      :id="selectedId"
      :read-only="readOnly"
      :app-id="currentApp.id"
      :app-name="currentApp.name"
      @close="editor = false"
      @saved="load"
    />
  </section>
</template>
