<template>
  <div class="workspace-module-page fa-full-height">
    <!-- 顶部独立筛选卡片（对齐系统标准规范） -->
    <ElCard v-show="showSearchBar" class="filter-card mb-3" shadow="never">
      <ElForm :model="searchForm" inline class="filter-form" @keyup.enter="handleSearch">
        <ElFormItem label="模块搜索">
          <ElInput
            v-model="searchForm.keyword"
            clearable
            placeholder="请输入模块名称或编码"
            :prefix-icon="Search"
            style="width: 220px"
          />
        </ElFormItem>
        <ElFormItem label="状态">
          <ElSelect
            v-model="searchForm.status"
            clearable
            placeholder="全部状态"
            style="width: 140px"
          >
            <ElOption value="active" label="可用" />
            <ElOption value="coming_soon" label="规划中" />
            <ElOption value="disabled" label="停用" />
          </ElSelect>
        </ElFormItem>
        <ElFormItem class="filter-actions">
          <ElButton @click="handleReset">
            <FaSvgIcon icon="ri:refresh-line" class="mr-1" />重置
          </ElButton>
          <ElButton type="primary" @click="handleSearch">
            <FaSvgIcon icon="ri:search-line" class="mr-1" />查询
          </ElButton>
        </ElFormItem>
      </ElForm>
    </ElCard>

    <!-- 主表格卡片（含系统规范 FaTableHeader 工具栏） -->
    <ElCard class="fa-table-card" shadow="never">
      <FaTableHeader
        v-model:columns="columnChecks"
        v-model:showSearchBar="showSearchBar"
        :loading="loading"
        @refresh="loadModules"
      >
        <!-- 左侧操作栏：新增按钮放左侧 -->
        <template #left>
          <div class="inline-flex items-center gap-2">
            <ElButton
              v-hasPerm="['module_system:module:add']"
              type="primary"
              @click="openCreate"
            >
              <FaSvgIcon icon="ri:add-line" class="mr-1" />新增工作台
            </ElButton>
            <span class="text-xs text-placeholder ml-2">共 {{ filteredModules.length }} 个工作台模块</span>
          </div>
        </template>
      </FaTableHeader>

      <!-- 标准表格 -->
      <ElTable
        v-loading="loading"
        :data="filteredModules"
        row-key="id"
        stripe
        border
        class="module-data-table mt-2"
      >
        <ElTableColumn
          v-if="isColumnVisible('order')"
          prop="order"
          label="排序"
          width="80"
          align="center"
        >
          <template #default="{ row }">
            <span class="order-badge">{{ row.order }}</span>
          </template>
        </ElTableColumn>

        <!-- 模块名称：去掉边框卡片盒子，直接显示图标（带配置色彩） -->
        <ElTableColumn
          v-if="isColumnVisible('name')"
          label="工作台模块"
          min-width="180"
        >
          <template #default="{ row }">
            <div class="module-name-cell">
              <!-- 直接显示图标，带配置的主题色，无多余边框卡片 -->
              <FaSvgIcon
                :icon="row.icon || 'ri:apps-line'"
                class="module-pure-icon"
                :style="{ color: row.accent || 'var(--el-color-primary)' }"
              />
              <div class="module-text-meta">
                <span class="name-title">{{ row.name }}</span>
                <span class="code-subtitle">{{ row.code }}</span>
              </div>
            </div>
          </template>
        </ElTableColumn>

        <ElTableColumn
          v-if="isColumnVisible('accent')"
          label="主题颜色"
          width="160"
        >
          <template #default="{ row }">
            <div class="color-cell">
              <span class="color-dot" :style="{ backgroundColor: row.accent || '#00BFFF' }" />
              <code class="color-text">{{ row.accent || "#00BFFF" }}</code>
            </div>
          </template>
        </ElTableColumn>

        <ElTableColumn
          v-if="isColumnVisible('description')"
          prop="description"
          label="模块业务说明"
          min-width="280"
          show-overflow-tooltip
        >
          <template #default="{ row }">
            <span class="desc-line">{{ row.description || "暂无说明" }}</span>
          </template>
        </ElTableColumn>

        <ElTableColumn
          v-if="isColumnVisible('menus')"
          label="关联菜单"
          width="110"
          align="center"
        >
          <template #default="{ row }">
            <ElTag v-if="row.menus?.length" size="small" type="info">
              {{ row.menus.length }} 个菜单
            </ElTag>
            <span v-else class="text-placeholder text-xs">无关联</span>
          </template>
        </ElTableColumn>

        <ElTableColumn
          v-if="isColumnVisible('status')"
          prop="status"
          label="状态"
          width="100"
          align="center"
        >
          <template #default="{ row }">
            <ElTag :type="getStatusTagType(row.status)" effect="light" size="small">
              {{ getStatusLabel(row.status) }}
            </ElTag>
          </template>
        </ElTableColumn>

        <ElTableColumn label="操作" width="140" align="center" fixed="right">
          <template #default="{ row }">
            <ElButton
              v-hasPerm="['module_system:module:update']"
              link
              type="primary"
              size="small"
              @click="openEdit(row)"
            >
              编辑
            </ElButton>
            <ElButton
              v-hasPerm="['module_system:module:delete']"
              link
              type="danger"
              size="small"
              @click="removeModule(row)"
            >
              删除
            </ElButton>
          </template>
        </ElTableColumn>

        <template #empty>
          <ElEmpty description="暂无符合条件的模块数据" />
        </template>
      </ElTable>
    </ElCard>

    <!-- 新增/编辑工作台弹窗 -->
    <ModuleEditor
      v-model="editorVisible"
      :module="editingModule"
      :submitting="submitting"
      :default-order="nextOrder"
      @save="saveModule"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from "vue";
import { Search } from "@element-plus/icons-vue";
import { ElMessage, ElMessageBox } from "element-plus";
import WorkspaceModuleAPI, {
  type WorkspaceModule,
  type WorkspaceModuleForm,
  type WorkspaceModuleStatus,
} from "@/api/module_system/module";
import ModuleEditor from "./components/module-editor.vue";

defineOptions({ name: "WorkspaceModuleManagement" });

const modules = ref<WorkspaceModule[]>([]);
const loading = ref(true);
const submitting = ref(false);
const editorVisible = ref(false);
const editingModule = ref<WorkspaceModule | null>(null);
const showSearchBar = ref(true);

// 顶部筛选表单
const searchForm = reactive<{
  keyword: string;
  status: WorkspaceModuleStatus | "";
}>({
  keyword: "",
  status: "",
});

// 列显隐配置
const columnChecks = ref([
  { prop: "order", label: "排序", visible: true },
  { prop: "name", label: "工作台模块", visible: true },
  { prop: "accent", label: "主题颜色", visible: true },
  { prop: "description", label: "模块业务说明", visible: true },
  { prop: "menus", label: "关联菜单", visible: true },
  { prop: "status", label: "状态", visible: true },
]);

function isColumnVisible(propName: string): boolean {
  const target = columnChecks.value.find((c) => c.prop === propName);
  return target ? target.visible : true;
}

// 新增时自动 +1 排序号
const nextOrder = computed(() => {
  if (!modules.value.length) return 1;
  const maxOrder = Math.max(...modules.value.map((m) => m.order || 0));
  return maxOrder + 1;
});

// 筛选后数据
const filteredModules = computed(() => {
  const term = searchForm.keyword.trim().toLocaleLowerCase();
  return modules.value.filter((item) => {
    const matchesKeyword =
      !term ||
      item.name.toLocaleLowerCase().includes(term) ||
      item.code.toLocaleLowerCase().includes(term);
    const matchesStatus = !searchForm.status || item.status === searchForm.status;
    return matchesKeyword && matchesStatus;
  });
});

function handleSearch(): void {
  // 纯客户端即时计算或触发刷新
}

function handleReset(): void {
  searchForm.keyword = "";
  searchForm.status = "";
}

function getStatusTagType(status: WorkspaceModuleStatus): "success" | "warning" | "info" {
  if (status === "active") return "success";
  if (status === "coming_soon") return "warning";
  return "info";
}

function getStatusLabel(status: WorkspaceModuleStatus): string {
  if (status === "active") return "可用";
  if (status === "coming_soon") return "规划中";
  return "已停用";
}

async function loadModules(): Promise<void> {
  loading.value = true;
  try {
    const response = await WorkspaceModuleAPI.list();
    modules.value = response.data.data ?? [];
  } finally {
    loading.value = false;
  }
}

function openCreate(): void {
  editingModule.value = null;
  editorVisible.value = true;
}

function openEdit(module: WorkspaceModule | any): void {
  editingModule.value = module as WorkspaceModule;
  editorVisible.value = true;
}

async function saveModule(form: WorkspaceModuleForm): Promise<void> {
  submitting.value = true;
  try {
    if (editingModule.value?.id) {
      await WorkspaceModuleAPI.update(editingModule.value.id, form);
    } else {
      await WorkspaceModuleAPI.create(form);
    }
    editorVisible.value = false;
    ElMessage.success("工作台模块已保存");
    await loadModules();
  } finally {
    submitting.value = false;
  }
}

async function removeModule(module: WorkspaceModule | any): Promise<void> {
  if (!module?.id) return;
  await ElMessageBox.confirm(
    `确认删除工作台模块“${module.name}”吗？若有关联菜单则无法删除。`,
    "删除工作台",
    { type: "warning" }
  );
  await WorkspaceModuleAPI.delete([module.id]);
  ElMessage.success("工作台已删除");
  await loadModules();
}

onMounted(loadModules);
</script>

<style scoped>
.workspace-module-page {
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
  padding: 16px;
  overflow: hidden;
  background: var(--app-bg);
}

.filter-card {
  border: 1px solid var(--el-border-color-lighter);
}

.filter-card :deep(.el-card__body) {
  padding: 14px 16px 2px;
}

.filter-actions {
  margin-left: auto;
}

.fa-table-card {
  display: flex;
  flex: 1 1 auto;
  flex-direction: column;
  overflow: hidden;
  border: 1px solid var(--el-border-color-lighter);
}

.fa-table-card :deep(.el-card__body) {
  display: flex;
  flex: 1 1 auto;
  flex-direction: column;
  height: 100%;
  padding: 14px 16px;
  overflow: hidden;
}

.module-data-table {
  flex: 1 1 auto;
  width: 100%;
}

.order-badge {
  display: inline-block;
  min-width: 24px;
  padding: 2px 6px;
  font-family: monospace;
  font-size: 12px;
  font-weight: 600;
  color: var(--el-text-color-regular);
  background: var(--el-fill-color-light);
  border-radius: 4px;
}

.module-name-cell {
  display: flex;
  gap: 12px;
  align-items: center;
}

/* 直接显示图标，带配置的主题色，无多余边框卡片 */
.module-pure-icon {
  flex: 0 0 22px;
  font-size: 22px;
  filter: drop-shadow(0 1px 2px rgb(0 0 0 / 12%));
}

.module-text-meta {
  display: flex;
  flex-direction: column;
}

.name-title {
  font-size: 14px;
  font-weight: 600;
  line-height: 1.3;
  color: var(--el-text-color-primary);
}

.code-subtitle {
  font-family: monospace;
  font-size: 11px;
  color: var(--el-text-color-placeholder);
}

.color-cell {
  display: flex;
  gap: 8px;
  align-items: center;
}

.color-dot {
  width: 14px;
  height: 14px;
  border: 1px solid rgb(0 0 0 / 12%);
  border-radius: 50%;
  box-shadow: 0 1px 3px rgb(0 0 0 / 10%);
}

.color-text {
  font-family: monospace;
  font-size: 12px;
  color: var(--el-text-color-regular);
}

.desc-line {
  font-size: 12.5px;
  line-height: 1.45;
  color: var(--el-text-color-secondary);
  white-space: pre-line;
}

.text-placeholder {
  color: var(--el-text-color-placeholder);
}
</style>
