<!-- 传输任务：远端/本地文件传输、进度查看、取消与删除 -->
<template>
  <div class="fa-full-height transfer-page">
    <ElCard shadow="never" class="search-card">
      <ElForm :model="query" inline @submit.prevent="handleSearch">
        <ElFormItem label="任务名称">
          <ElInput
            v-model="query.name"
            placeholder="请输入任务名称"
            clearable
            style="width: 220px"
            @keyup.enter="handleSearch"
          />
        </ElFormItem>
        <ElFormItem label="任务类型">
          <ElSelect v-model="query.task_type" placeholder="全部类型" clearable style="width: 160px">
            <ElOption label="多目标并行" value="parallel" />
            <ElOption label="顺序链式" value="chain" />
          </ElSelect>
        </ElFormItem>
        <ElFormItem label="状态">
          <ElSelect v-model="query.status" placeholder="全部状态" clearable style="width: 140px">
            <ElOption v-for="option in statusOptions" :key="option.value" v-bind="option" />
          </ElSelect>
        </ElFormItem>
        <ElFormItem>
          <ElButton type="primary" @click="handleSearch">查询</ElButton>
          <ElButton @click="resetSearch">重置</ElButton>
        </ElFormItem>
      </ElForm>
    </ElCard>

    <ElCard shadow="never" class="table-card">
      <div class="table-toolbar">
        <div class="flex gap-2">
          <ElButton
            v-hasPerm="['module_storage:transfer:create']"
            type="primary"
            :icon="Plus"
            @click="openCreate"
          >
            新建传输
          </ElButton>
          <ElButton
            v-hasPerm="['module_storage:transfer:delete']"
            :icon="Delete"
            :disabled="selectedIds.length === 0"
            @click="deleteSelected"
          >
            批量删除
          </ElButton>
        </div>
        <ElButton :icon="Refresh" :loading="loading" circle title="刷新" @click="loadTasks()" />
      </div>

      <ElTable
        v-loading="loading"
        :data="tasks"
        row-key="id"
        height="100%"
        @selection-change="onSelectionChange"
      >
        <ElTableColumn type="selection" width="48" />
        <ElTableColumn label="任务名称" prop="name" min-width="170" show-overflow-tooltip />
        <ElTableColumn label="类型" width="110">
          <template #default="{ row }">
            {{ row.task_type === "parallel" ? "多目标并行" : "顺序链式" }}
          </template>
        </ElTableColumn>
        <ElTableColumn label="来源" min-width="180" show-overflow-tooltip>
          <template #default="{ row }">
            <span v-if="row.source_type === 'local'">本地文件：{{ row.source_name || "-" }}</span>
            <span v-else>{{ sourceName(row.source_id) }} / {{ row.source_path || "-" }}</span>
          </template>
        </ElTableColumn>
        <ElTableColumn label="状态" width="95" align="center">
          <template #default="{ row }">
            <ElTag :type="statusMeta(row.status).type" effect="light">
              {{ statusMeta(row.status).label }}
            </ElTag>
          </template>
        </ElTableColumn>
        <ElTableColumn label="进度" min-width="190">
          <template #default="{ row }">
            <ElProgress
              :percentage="row.progress || 0"
              :stroke-width="8"
              :status="progressStatus(row.status)"
            />
          </template>
        </ElTableColumn>
        <ElTableColumn label="已传输 / 总大小" width="170">
          <template #default="{ row }">
            {{ formatSize(row.transferred_size) }} /
            {{ formatSize(row.total_size || row.source_size) }}
          </template>
        </ElTableColumn>
        <ElTableColumn label="速度" width="110">
          <template #default="{ row }">{{ formatSpeed(row.speed) }}</template>
        </ElTableColumn>
        <ElTableColumn label="创建时间" prop="created_time" width="170" show-overflow-tooltip />
        <ElTableColumn label="操作" width="190" fixed="right" align="center">
          <template #default="{ row }">
            <ElButton link type="primary" @click="openDetail(row.id)">详情</ElButton>
            <ElButton
              v-if="row.status === 'pending' || row.status === 'running'"
              v-hasPerm="['module_storage:transfer:update']"
              link
              type="warning"
              @click="cancelTask(row)"
            >
              取消
            </ElButton>
            <ElButton
              v-hasPerm="['module_storage:transfer:delete']"
              link
              type="danger"
              @click="deleteTask(row)"
            >
              删除
            </ElButton>
          </template>
        </ElTableColumn>
        <template #empty>
          <ElEmpty description="暂无传输任务" :image-size="90" />
        </template>
      </ElTable>

      <div class="pagination-wrap">
        <ElPagination
          v-model:current-page="query.page_no"
          v-model:page-size="query.page_size"
          :total="total"
          :page-sizes="[10, 20, 50, 100]"
          layout="total, sizes, prev, pager, next, jumper"
          @size-change="handleSizeChange"
          @current-change="loadTasks()"
        />
      </div>
    </ElCard>

    <ElDialog
      v-model="createVisible"
      title="新建传输任务"
      width="760px"
      :close-on-click-modal="false"
      @closed="resetCreateForm"
    >
      <ElForm ref="createFormRef" :model="createForm" :rules="createRules" label-width="100px">
        <ElFormItem label="任务名称" prop="name">
          <ElInput
            v-model="createForm.name"
            placeholder="请输入任务名称"
            maxlength="128"
            show-word-limit
          />
        </ElFormItem>
        <div class="form-grid">
          <ElFormItem label="源类型" prop="source_type">
            <ElRadioGroup v-model="createForm.source_type" @change="onSourceTypeChange">
              <ElRadioButton value="remote">存储源文件</ElRadioButton>
              <ElRadioButton value="local">本地上传</ElRadioButton>
            </ElRadioGroup>
          </ElFormItem>
          <ElFormItem label="执行方式" prop="task_type">
            <ElSelect v-model="createForm.task_type" class="w-full">
              <ElOption label="多目标并行" value="parallel" />
              <ElOption label="顺序链式" value="chain" />
            </ElSelect>
          </ElFormItem>
        </div>

        <template v-if="createForm.source_type === 'remote'">
          <div class="form-grid">
            <ElFormItem label="源存储" required>
              <ElSelect
                v-model="createForm.source_id"
                filterable
                placeholder="请选择源存储"
                class="w-full"
              >
                <ElOption
                  v-for="source in sourceOptions"
                  :key="source.id"
                  :label="source.name"
                  :value="source.id!"
                />
              </ElSelect>
            </ElFormItem>
            <ElFormItem label="源文件路径" required>
              <ElInput v-model="createForm.source_path" placeholder="例如：data/source.zip" />
            </ElFormItem>
          </div>
        </template>
        <ElFormItem v-else label="本地文件" required>
          <ElUpload
            :auto-upload="false"
            :limit="1"
            :on-change="onLocalFileChange"
            :on-remove="onLocalFileRemove"
          >
            <ElButton type="primary" plain>选择文件</ElButton>
            <template #tip>
              <div class="el-upload__tip">文件将在创建任务后上传并立即开始传输</div>
            </template>
          </ElUpload>
        </ElFormItem>

        <ElFormItem label="传输目标" required>
          <div class="target-list">
            <div v-for="(target, index) in createForm.targets" :key="index" class="target-row">
              <ElSelect v-model="target.target_id" filterable placeholder="目标存储源">
                <ElOption
                  v-for="source in sourceOptions"
                  :key="source.id"
                  :label="source.name"
                  :value="source.id!"
                />
              </ElSelect>
              <ElInput v-model="target.target_path" placeholder="目标文件路径" />
              <ElButton
                :icon="Delete"
                circle
                :disabled="createForm.targets.length === 1"
                @click="removeTarget(index)"
              />
            </div>
            <ElButton link type="primary" :icon="Plus" @click="addTarget">添加目标</ElButton>
            <div v-if="createForm.task_type === 'chain'" class="target-tip">
              链式任务将按列表顺序依次传输，后一步以前一步的目标文件为来源。
            </div>
          </div>
        </ElFormItem>
      </ElForm>
      <template #footer>
        <ElButton @click="createVisible = false">取消</ElButton>
        <ElButton type="primary" :loading="submitting" @click="submitCreate">创建并开始</ElButton>
      </template>
    </ElDialog>

    <ElDialog v-model="detailVisible" title="传输任务详情" width="900px">
      <template v-if="detailTaskData">
        <ElDescriptions :column="3" border>
          <ElDescriptionsItem label="任务名称" :span="2">{{
            detailTaskData.name
          }}</ElDescriptionsItem>
          <ElDescriptionsItem label="状态">
            <ElTag :type="statusMeta(detailTaskData.status).type">
              {{ statusMeta(detailTaskData.status).label }}
            </ElTag>
          </ElDescriptionsItem>
          <ElDescriptionsItem label="任务类型">
            {{ detailTaskData.task_type === "parallel" ? "多目标并行" : "顺序链式" }}
          </ElDescriptionsItem>
          <ElDescriptionsItem label="来源类型">
            {{ detailTaskData.source_type === "local" ? "本地上传" : "存储源文件" }}
          </ElDescriptionsItem>
          <ElDescriptionsItem label="源文件">{{
            detailTaskData.source_name || detailTaskData.source_path || "-"
          }}</ElDescriptionsItem>
          <ElDescriptionsItem label="总进度" :span="2">
            <ElProgress
              :percentage="detailTaskData.progress || 0"
              :status="progressStatus(detailTaskData.status)"
            />
          </ElDescriptionsItem>
          <ElDescriptionsItem label="实时速度">{{
            formatSpeed(detailTaskData.speed)
          }}</ElDescriptionsItem>
          <ElDescriptionsItem label="开始时间">{{
            detailTaskData.started_at || "-"
          }}</ElDescriptionsItem>
          <ElDescriptionsItem label="完成时间">{{
            detailTaskData.finished_at || "-"
          }}</ElDescriptionsItem>
          <ElDescriptionsItem label="错误信息" :span="3">
            <span :class="detailTaskData.error_msg ? 'text-red-500' : ''">
              {{ detailTaskData.error_msg || "-" }}
            </span>
          </ElDescriptionsItem>
        </ElDescriptions>

        <div class="detail-section-title">传输步骤</div>
        <ElTable :data="detailTaskData.steps || []" border max-height="360">
          <ElTableColumn label="#" width="55">
            <template #default="{ row }">{{ row.step_order + 1 }}</template>
          </ElTableColumn>
          <ElTableColumn label="目标存储" width="150">
            <template #default="{ row }">{{ sourceName(row.target_id) }}</template>
          </ElTableColumn>
          <ElTableColumn
            label="目标路径"
            prop="target_path"
            min-width="190"
            show-overflow-tooltip
          />
          <ElTableColumn label="状态" width="90">
            <template #default="{ row }">{{ statusMeta(row.status).label }}</template>
          </ElTableColumn>
          <ElTableColumn label="进度" min-width="160">
            <template #default="{ row }"
              ><ElProgress :percentage="row.progress || 0" :stroke-width="7"
            /></template>
          </ElTableColumn>
          <ElTableColumn label="错误信息" prop="error_msg" min-width="160" show-overflow-tooltip />
        </ElTable>
      </template>
      <template #footer>
        <ElButton @click="detailVisible = false">关闭</ElButton>
      </template>
    </ElDialog>
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, reactive, ref } from "vue";
import { Delete, Plus, Refresh } from "@element-plus/icons-vue";
import {
  ElMessage,
  ElMessageBox,
  type FormInstance,
  type FormRules,
  type UploadFile,
} from "element-plus";
import TransferAPI, {
  type TransferSourceType,
  type TransferStatus,
  type TransferTask,
  type TransferTaskQuery,
  type TransferTaskType,
} from "@/api/module_storage/transfer";
import SourceAPI, { type SourceTable } from "@/api/module_storage/source";

defineOptions({
  name: "StorageTransfer",
  inheritAttrs: false,
});

const statusOptions = [
  { label: "等待中", value: "pending" },
  { label: "传输中", value: "running" },
  { label: "已完成", value: "success" },
  { label: "失败", value: "failed" },
  { label: "已取消", value: "canceled" },
];

const query = reactive<TransferTaskQuery>({ page_no: 1, page_size: 10 });
const tasks = ref<TransferTask[]>([]);
const total = ref(0);
const loading = ref(false);
const selectedIds = ref<number[]>([]);
const sourceOptions = ref<SourceTable[]>([]);

function statusMeta(status: TransferStatus) {
  const map = {
    pending: { label: "等待中", type: "info" as const },
    running: { label: "传输中", type: "primary" as const },
    success: { label: "已完成", type: "success" as const },
    failed: { label: "失败", type: "danger" as const },
    canceled: { label: "已取消", type: "warning" as const },
  };
  return map[status] || map.pending;
}

function progressStatus(status: TransferStatus): "success" | "exception" | "warning" | undefined {
  if (status === "success") return "success";
  if (status === "failed") return "exception";
  if (status === "canceled") return "warning";
  return undefined;
}

function formatSize(size?: number | null): string {
  if (!size) return "0 B";
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  if (size < 1024 * 1024 * 1024) return `${(size / 1024 / 1024).toFixed(2)} MB`;
  return `${(size / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

function formatSpeed(speed?: number | null): string {
  return speed ? `${formatSize(speed)}/s` : "-";
}

function sourceName(id?: number | null): string {
  return (
    sourceOptions.value.find((source) => source.id === id)?.name || (id ? `存储源 #${id}` : "-")
  );
}

async function loadSources() {
  const response = await SourceAPI.listSource({ status: 0 });
  sourceOptions.value = response.data?.data ?? [];
}

async function loadTasks(silent = false) {
  if (!silent) loading.value = true;
  try {
    const response = await TransferAPI.pageTask(query);
    tasks.value = response.data?.data?.items ?? [];
    total.value = response.data?.data?.total ?? 0;
  } finally {
    if (!silent) loading.value = false;
  }
}

function handleSearch() {
  query.page_no = 1;
  void loadTasks();
}

function resetSearch() {
  query.name = undefined;
  query.task_type = undefined;
  query.status = undefined;
  query.page_no = 1;
  void loadTasks();
}

function handleSizeChange() {
  query.page_no = 1;
  void loadTasks();
}

function onSelectionChange(rows: TransferTask[]) {
  selectedIds.value = rows.flatMap((row) => (row.id ? [row.id] : []));
}

const createVisible = ref(false);
const submitting = ref(false);
const createFormRef = ref<FormInstance>();
const localFile = ref<File>();

interface TargetDraft {
  target_id?: number;
  target_path: string;
}

interface TransferCreateDraft {
  name: string;
  task_type: TransferTaskType;
  source_type: TransferSourceType;
  source_id?: number;
  source_path: string;
  targets: TargetDraft[];
}

const createForm = reactive<TransferCreateDraft>({
  name: "",
  task_type: "parallel",
  source_type: "remote",
  source_id: undefined,
  source_path: "",
  targets: [{ target_id: undefined, target_path: "" }],
});

const createRules: FormRules<TransferCreateDraft> = {
  name: [{ required: true, message: "请输入任务名称", trigger: "blur" }],
  task_type: [{ required: true, message: "请选择执行方式", trigger: "change" }],
  source_type: [{ required: true, message: "请选择源类型", trigger: "change" }],
};

function openCreate() {
  createVisible.value = true;
}

function resetCreateForm() {
  createFormRef.value?.resetFields();
  Object.assign(createForm, {
    name: "",
    task_type: "parallel",
    source_type: "remote",
    source_id: undefined,
    source_path: "",
    targets: [{ target_id: undefined, target_path: "" }],
  });
  localFile.value = undefined;
}

function onSourceTypeChange() {
  createForm.source_id = undefined;
  createForm.source_path = "";
  localFile.value = undefined;
}

function onLocalFileChange(file: UploadFile) {
  localFile.value = file.raw;
}

function onLocalFileRemove() {
  localFile.value = undefined;
}

function addTarget() {
  createForm.targets.push({ target_id: undefined, target_path: "" });
}

function removeTarget(index: number) {
  createForm.targets.splice(index, 1);
}

async function submitCreate() {
  const valid = await createFormRef.value?.validate().catch(() => false);
  if (!valid) return;
  if (
    createForm.source_type === "remote" &&
    (!createForm.source_id || !createForm.source_path.trim())
  ) {
    ElMessage.warning("请选择源存储并填写源文件路径");
    return;
  }
  if (createForm.source_type === "local" && !localFile.value) {
    ElMessage.warning("请选择本地文件");
    return;
  }
  if (createForm.targets.some((target) => !target.target_id || !target.target_path.trim())) {
    ElMessage.warning("请完整填写每个传输目标");
    return;
  }

  const targets = createForm.targets.map((target) => ({
    target_id: target.target_id!,
    target_path: target.target_path.trim(),
  }));
  submitting.value = true;
  try {
    if (createForm.source_type === "remote") {
      await TransferAPI.createRemoteTask({
        name: createForm.name.trim(),
        task_type: createForm.task_type,
        source_type: "remote",
        source_id: createForm.source_id!,
        source_path: createForm.source_path.trim(),
        targets,
      });
    } else {
      const formData = new FormData();
      formData.append("file", localFile.value!);
      formData.append("name", createForm.name.trim());
      formData.append("task_type", createForm.task_type);
      formData.append("targets", JSON.stringify(targets));
      await TransferAPI.createLocalTask(formData);
    }
    ElMessage.success("传输任务已创建");
    createVisible.value = false;
    query.page_no = 1;
    await loadTasks();
  } finally {
    submitting.value = false;
  }
}

const detailVisible = ref(false);
const detailTaskData = ref<TransferTask>();

async function openDetail(id?: number) {
  if (!id) return;
  const response = await TransferAPI.detailTask(id);
  detailTaskData.value = response.data?.data;
  detailVisible.value = true;
}

async function cancelTask(row: unknown) {
  const task = row as TransferTask;
  if (!task.id) return;
  await ElMessageBox.confirm(`确定取消传输任务「${task.name}」吗？`, "确认取消", {
    type: "warning",
  });
  await TransferAPI.cancelTask(task.id);
  ElMessage.success("已请求取消传输任务");
  await loadTasks();
}

async function deleteTask(row: unknown) {
  const task = row as TransferTask;
  if (!task.id) return;
  await ElMessageBox.confirm(`确定删除传输任务「${task.name}」吗？`, "确认删除", {
    type: "warning",
  });
  await TransferAPI.deleteTask([task.id]);
  ElMessage.success("删除成功");
  await loadTasks();
}

async function deleteSelected() {
  if (!selectedIds.value.length) return;
  await ElMessageBox.confirm(
    `确定删除选中的 ${selectedIds.value.length} 个传输任务吗？`,
    "批量删除",
    {
      type: "warning",
    }
  );
  await TransferAPI.deleteTask(selectedIds.value);
  ElMessage.success("删除成功");
  await loadTasks();
}

let refreshTimer: ReturnType<typeof setInterval> | undefined;

onMounted(async () => {
  await Promise.all([loadSources(), loadTasks()]);
  refreshTimer = setInterval(() => {
    if (tasks.value.some((task) => task.status === "pending" || task.status === "running")) {
      void loadTasks(true);
    }
  }, 5000);
});

onBeforeUnmount(() => {
  if (refreshTimer) clearInterval(refreshTimer);
});
</script>

<style scoped>
.transfer-page {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-height: 0;
}

.search-card :deep(.el-card__body) {
  padding-bottom: 2px;
}

.table-card {
  flex: 1;
  min-height: 0;
}

.table-card :deep(.el-card__body) {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.table-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.pagination-wrap {
  display: flex;
  justify-content: flex-end;
  padding-top: 14px;
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.target-list {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 10px;
}

.target-row {
  display: grid;
  grid-template-columns: 200px minmax(0, 1fr) 32px;
  gap: 10px;
}

.target-tip {
  font-size: 12px;
  line-height: 1.5;
  color: var(--el-text-color-secondary);
}

.detail-section-title {
  margin: 20px 0 10px;
  font-weight: 600;
}

@media (width <= 760px) {
  .form-grid {
    grid-template-columns: 1fr;
  }

  .target-row {
    grid-template-columns: 1fr;
  }
}
</style>
