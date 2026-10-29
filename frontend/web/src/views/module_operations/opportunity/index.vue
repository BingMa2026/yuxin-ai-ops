<template>
  <main class="opportunity-page fa-full-height">
    <FaSearchBar
      v-if="currentApp"
      v-show="showSearchBar"
      :model-value="query"
      :items="searchItems"
      :is-expand="false"
      :show-expand="false"
      :disabled-search="true"
      @update:model-value="Object.assign(query, $event)"
      @reset="handleReset"
    />
    <ElCard
      v-if="currentApp"
      class="fa-table-card"
      :style="{ 'margin-top': showSearchBar ? '12px' : '0' }"
    >
      <FaTableHeader
        v-model:columns="columnChecks"
        v-model:showSearchBar="showSearchBar"
        :show-refresh="false"
      />
      <FaTable :data="[]" :columns="columns" :pagination="pagination" />
    </ElCard>
    <ElCard v-else class="fa-table-card"><ElEmpty description="请先在顶栏选择客户端" /></ElCard>
  </main>
</template>

<script setup lang="ts">
import type { SearchFormItem } from "@/components/forms/fa-search-bar/index.vue";
import FaTableHeader from "@/components/tables/fa-table-header/index.vue";
import { useClientAppStore } from "@stores";

defineOptions({ name: "OpportunityResources" });

interface OpportunityRow {
  id: number;
  project_name: string;
  purchaser: string;
  region: string;
  stage: string;
  owner: string;
  updated_time: string;
}

const { currentApp } = storeToRefs(useClientAppStore());
const query = reactive({ keyword: "", stage: "", range: [] as string[] });
const showSearchBar = ref(true);
const searchItems: SearchFormItem[] = [
  {
    label: "关键词",
    key: "keyword",
    type: "input",
    placeholder: "项目名称、招标人或地区",
    props: { clearable: true, disabled: true },
    span: 8,
  },
  {
    label: "阶段",
    key: "stage",
    type: "select",
    props: {
      placeholder: "请选择阶段",
      clearable: true,
      disabled: true,
      options: [{ label: "跟进中", value: "tracking" }],
    },
    span: 8,
  },
  {
    label: "更新时间",
    key: "range",
    type: "datetimerange",
    props: { disabled: true, valueFormat: "YYYY-MM-DD HH:mm:ss" },
    span: 8,
  },
];
const { columnChecks, columns } = useTableColumns<OpportunityRow>(() => [
  { type: "globalIndex", width: 56, label: "序号" },
  { prop: "project_name", label: "项目名称", minWidth: 190 },
  { prop: "purchaser", label: "招标人", minWidth: 150 },
  { prop: "region", label: "地区", width: 110 },
  { prop: "stage", label: "阶段", width: 100 },
  { prop: "owner", label: "负责人", width: 120 },
  { prop: "updated_time", label: "更新时间", width: 168 },
]);
const pagination = { current: 1, size: 10, total: 0 };

function handleReset() {
  Object.assign(query, { keyword: "", stage: "", range: [] });
}
</script>

<style scoped>
.opportunity-page {
  min-height: 0;
}
</style>
