<template>
  <main class="client-workspace fa-full-height">
    <aside class="client-panel">
      <div class="client-search">
        <ElInput v-model="keyword" clearable placeholder="搜索名称或编码"
          ><template #prefix><FaSvgIcon icon="ri:search-line" /></template
        ></ElInput>
        <ElButton
          v-hasPerm="['workspace:budget:product:create']"
          class="create-client-button"
          type="primary"
          aria-label="新增客户端"
          title="新增客户端"
          @click="openCreate"
          ><FaSvgIcon icon="ri:add-line"
        /></ElButton>
      </div>
      <div class="status-filter">
        <button
          v-for="option in statusOptions"
          :key="option.value"
          :class="{ active: statusFilter === option.value }"
          @click="statusFilter = option.value"
        >
          {{ option.label }}
        </button>
      </div>
      <div class="client-list" v-loading="loading">
        <button
          v-for="item in filteredApps"
          :key="item.id"
          class="client-item"
          :class="{ active: selected?.id === item.id }"
          @click="selectApp(item)"
        >
          <span class="app-logo"
            ><img v-if="item.logo" :src="item.logo" :alt="item.name" /><b v-else>{{
              item.name.slice(0, 1)
            }}</b></span
          >
          <span class="client-copy"
            ><strong>{{ item.name }}</strong
            ><small>{{ item.code }} · {{ item.client_version || "暂无版本" }}</small></span
          >
          <i :class="`status-${item.status}`">{{ statusName(item.status) }}</i>
        </button>
        <ElEmpty
          v-if="!filteredApps.length && !loading"
          description="暂无客户端"
          :image-size="70"
        />
      </div>
    </aside>

    <section v-if="selected" class="detail-panel">
      <header class="detail-head">
        <span class="hero-logo"
          ><img v-if="selected.logo" :src="selected.logo" /><b v-else>{{
            selected.name.slice(0, 1)
          }}</b></span
        >
        <div class="hero-copy">
          <div>
            <h2>{{ selected.name }}</h2>
            <ElTag :type="statusType(selected.status)" effect="light">{{
              statusName(selected.status)
            }}</ElTag>
          </div>
          <p>{{ selected.description || "暂无客户端介绍" }}</p>
          <span
            >{{ selected.code }} · Windows x64 · 当前版本
            {{ selected.client_version || "未发布" }}</span
          >
        </div>
        <ElButton
          v-if="selected.status === 'active' && selected.id !== currentApp?.id"
          @click="enterApp(selected)"
          >进入运营</ElButton
        >
      </header>

      <ElTabs v-model="activeTab" class="detail-tabs">
        <ElTabPane label="基本资料" name="profile">
          <div class="tab-scroll profile-layout">
            <section class="info-card">
              <div class="card-head">
                <strong>产品信息</strong
                ><ElButton
                  v-hasPerm="['workspace:budget:product:update']"
                  @click="openEdit(selected)"
                  >编辑资料</ElButton
                >
              </div>
              <dl class="info-grid">
                <div>
                  <dt>客户端名称</dt>
                  <dd>{{ selected.name }}</dd>
                </div>
                <div>
                  <dt>稳定编码</dt>
                  <dd>{{ selected.code }}</dd>
                </div>
                <div>
                  <dt>运行状态</dt>
                  <dd>
                    <ElTag :type="statusType(selected.status)">{{
                      statusName(selected.status)
                    }}</ElTag>
                  </dd>
                </div>
                <div>
                  <dt>开放注册</dt>
                  <dd>
                    <ElTag :type="selected.registration_enabled ? 'success' : 'info'">{{
                      selected.registration_enabled ? "已开放" : "未开放"
                    }}</ElTag>
                  </dd>
                </div>
                <div>
                  <dt>模型服务</dt>
                  <dd>
                    {{ serviceModeLabel(selected.service_mode) }}
                  </dd>
                </div>
                <div>
                  <dt>显示排序</dt>
                  <dd>{{ selected.order }}</dd>
                </div>
                <div>
                  <dt>更新通道</dt>
                  <dd>
                    /public/client-apps/{{ selected.code }}/updates/windows/x64/stable/latest.yml
                  </dd>
                </div>
              </dl>
            </section>
            <section class="info-card release-summary">
              <div class="card-head">
                <strong>发布概况</strong
                ><ElButton text type="primary" @click="activeTab = 'releases'">管理版本</ElButton>
              </div>
              <div class="summary-grid">
                <div>
                  <span>正式版</span
                  ><strong>{{ latestRelease("stable")?.version || "未发布" }}</strong>
                </div>
                <div>
                  <span>测试版</span
                  ><strong>{{ latestRelease("test")?.version || "未发布" }}</strong>
                </div>
                <div>
                  <span>版本总数</span><strong>{{ releases.length }}</strong>
                </div>
              </div>
            </section>
          </div>
        </ElTabPane>

        <ElTabPane label="版本发布" name="releases">
          <div class="tab-scroll">
            <div class="section-tools">
              <div><strong>Windows 版本</strong><span>支持平台上传或 HTTPS 外链</span></div>
              <ElButton type="primary" @click="openRelease">创建版本</ElButton>
            </div>
            <div class="release-list" v-loading="releaseLoading">
              <article v-for="item in releases" :key="item.id">
                <div class="release-icon"><FaSvgIcon icon="ri:windows-fill" /></div>
                <div class="release-main">
                  <div>
                    <strong>v{{ item.version }}</strong
                    ><ElTag
                      size="small"
                      :type="item.channel === 'stable' ? 'success' : 'warning'"
                      >{{ item.channel === "stable" ? "正式渠道" : "测试渠道" }}</ElTag
                    ><ElTag size="small" :type="releaseStatusType(item.status)">{{
                      releaseStatusName(item.status)
                    }}</ElTag>
                  </div>
                  <p>{{ item.release_notes || "暂无更新说明" }}</p>
                  <span
                    >{{
                      item.published_at
                        ? `发布于 ${item.published_at}`
                        : `创建于 ${item.created_time}`
                    }}
                    · {{ artifactName(item) }}</span
                  >
                </div>
                <div class="release-actions">
                  <ElButton v-if="item.status === 'draft'" type="primary" @click="editRelease(item)"
                    >完善并发布</ElButton
                  ><ElButton
                    v-if="item.status === 'published'"
                    type="danger"
                    plain
                    @click="withdraw(item)"
                    >撤回</ElButton
                  >
                </div>
              </article>
              <ElEmpty v-if="!releases.length && !releaseLoading" description="还没有发布版本" />
            </div>
          </div>
        </ElTabPane>

        <ElTabPane label="运营人员" name="staff">
          <div class="tab-scroll staff-page" v-loading="staffLoading">
            <div class="section-tools">
              <div><strong>运营权限</strong><span>被授权人员可查看和运营当前客户端数据</span></div>
              <ElButton type="primary" :loading="staffSaving" @click="saveStaff">保存授权</ElButton>
            </div>
            <ElCheckboxGroup v-model="selectedStaffIds" class="staff-grid"
              ><ElCheckbox v-for="item in staffOptions" :key="item.id" :value="item.id" border
                ><span class="staff-avatar">{{ item.name.slice(0, 1) }}</span
                ><span
                  ><strong>{{ item.name }}</strong
                  ><small>{{ item.username }}</small></span
                ></ElCheckbox
              ></ElCheckboxGroup
            >
          </div>
        </ElTabPane>
      </ElTabs>
    </section>
    <section v-else class="detail-panel empty-detail">
      <ElEmpty description="请选择客户端" />
    </section>

    <ClientAppEditor v-model="editorVisible" :app="editing" :saving="saving" @save="save" />
    <ElDialog
      v-model="releaseDialog"
      :title="editingRelease ? `发布 v${editingRelease.version}` : '创建 Windows 版本'"
      width="min(720px, 94vw)"
      destroy-on-close
    >
      <ElForm label-position="top">
        <div class="form-grid">
          <ElFormItem label="版本号"
            ><ElInput
              v-model="releaseForm.version"
              :disabled="!!editingRelease"
              placeholder="例如 1.2.0" /></ElFormItem
          ><ElFormItem label="发布渠道"
            ><ElSelect v-model="releaseForm.channel" :disabled="!!editingRelease"
              ><ElOption label="测试渠道" value="test" /><ElOption
                label="正式渠道"
                value="stable" /></ElSelect></ElFormItem
          ><ElFormItem label="最低兼容版本"
            ><ElInput
              v-model="releaseForm.min_supported_version"
              placeholder="留空表示不限制" /></ElFormItem
          ><ElFormItem label="更新方式"
            ><ElCheckbox v-model="releaseForm.force_update">强制更新</ElCheckbox></ElFormItem
          >
        </div>
        <ElFormItem label="更新说明"
          ><ElInput
            v-model="releaseForm.release_notes"
            type="textarea"
            :rows="5"
            placeholder="逐条说明本次新增、优化和修复内容"
        /></ElFormItem>
        <ElDivider content-position="left">安装制品</ElDivider
        ><ElRadioGroup v-model="artifactMode"
          ><ElRadioButton value="external">HTTPS 外链</ElRadioButton
          ><ElRadioButton value="upload">平台上传</ElRadioButton></ElRadioGroup
        >
        <template v-if="artifactMode === 'external'"
          ><ElFormItem label="安装包 HTTPS 地址"
            ><ElInput
              v-model="artifactForm.external_url"
              placeholder="https://download.example.com/app-1.2.0.exe"
          /></ElFormItem>
          <div class="form-grid">
            <ElFormItem label="文件名"><ElInput v-model="artifactForm.file_name" /></ElFormItem
            ><ElFormItem label="文件大小（字节）"
              ><ElInputNumber v-model="artifactForm.file_size" :min="0"
            /></ElFormItem></div
        ></template>
        <template v-else
          ><ElUpload :auto-upload="false" :limit="1" drag @change="onReleaseFile"
            ><FaSvgIcon icon="ri:upload-cloud-2-line" />
            <div>拖入或点击选择 EXE/MSI/MSIX 安装包</div></ElUpload
          ><ElProgress
            v-if="uploadProgress > 0"
            :percentage="uploadProgress"
            class="upload-progress"
        /></template>
        <ElFormItem label="SHA-512"
          ><ElInput
            v-model="artifactForm.sha512"
            type="textarea"
            :rows="2"
            placeholder="electron-builder 生成的 SHA-512 校验值" /></ElFormItem
        ><ElCheckbox v-model="artifactForm.signature_verified">安装包已通过数字签名验证</ElCheckbox>
        <p v-if="releaseForm.channel === 'stable'" class="form-tip">
          正式渠道必须使用 HTTPS、填写 SHA-512，并确认数字签名；测试渠道允许未签名安装包。
        </p>
      </ElForm>
      <template #footer
        ><ElButton @click="releaseDialog = false">取消</ElButton
        ><ElButton type="primary" :loading="releaseSaving" @click="saveRelease">{{
          editingRelease ? "保存并发布" : "创建草稿"
        }}</ElButton></template
      >
    </ElDialog>
  </main>
</template>

<script setup lang="ts">
import { serviceModeLabel } from "@/api/module_client/app";
import { ElMessage, ElMessageBox, type UploadFile } from "element-plus";
import ClientAppAPI, {
  type ClientAppForm,
  type ClientAppInfo,
  type ClientAppStaffOption,
  type ClientRelease,
} from "@/api/module_client/app";
import { useClientAppStore, useUserStore } from "@stores";
import { HttpError } from "@/utils/http";
import ClientAppEditor from "./components/ClientAppEditor.vue";

defineOptions({ name: "BudgetProductManagement" });
const apps = ref<ClientAppInfo[]>([]);
const selected = ref<ClientAppInfo>();
const releases = ref<ClientRelease[]>([]);
const loading = ref(false);
const releaseLoading = ref(false);
const keyword = ref("");
const statusFilter = ref("");
const activeTab = ref("profile");
const editorVisible = ref(false);
const editing = ref<ClientAppInfo>();
const saving = ref(false);
const releaseDialog = ref(false);
const releaseSaving = ref(false);
const editingRelease = ref<ClientRelease>();
const artifactMode = ref<"external" | "upload">("external");
const releaseFile = ref<File>();
const uploadProgress = ref(0);
const staffOptions = ref<ClientAppStaffOption[]>([]);
const selectedStaffIds = ref<number[]>([]);
const staffLoading = ref(false);
const staffSaving = ref(false);
const clientAppStore = useClientAppStore();
const { currentApp } = storeToRefs(clientAppStore);
const userStore = useUserStore();
const statusOptions = [
  { label: "全部", value: "" },
  { label: "运营中", value: "active" },
  { label: "草稿", value: "draft" },
  { label: "已停用", value: "inactive" },
];
const releaseForm = reactive({
  version: "",
  channel: "test" as "stable" | "test",
  release_notes: "",
  min_supported_version: "",
  force_update: false,
});
const artifactForm = reactive({
  external_url: "",
  file_name: "",
  file_size: 0,
  sha512: "",
  signature_verified: false,
});
const filteredApps = computed(() =>
  apps.value.filter(
    (item) =>
      (!statusFilter.value || item.status === statusFilter.value) &&
      (!keyword.value ||
        `${item.name}${item.code}`.toLowerCase().includes(keyword.value.toLowerCase()))
  )
);
function statusName(value: string) {
  return (
    ({ draft: "草稿", active: "运营中", inactive: "已停用" } as Record<string, string>)[value] ||
    value
  );
}
function statusType(value: string) {
  return value === "active" ? "success" : value === "inactive" ? "danger" : "info";
}
function releaseStatusName(value: string) {
  return (
    ({ draft: "草稿", published: "已发布", withdrawn: "已撤回" } as Record<string, string>)[
      value
    ] || value
  );
}
function releaseStatusType(value: string) {
  return value === "published" ? "success" : value === "withdrawn" ? "danger" : "info";
}
function latestRelease(channel: string) {
  return releases.value.find((item) => item.channel === channel && item.status === "published");
}
function artifactName(item: ClientRelease) {
  return (
    item.artifacts.find((artifact) => artifact.artifact_type === "installer")?.file_name ||
    "未配置安装包"
  );
}
async function loadApps() {
  loading.value = true;
  try {
    const response = await ClientAppAPI.list({ page_no: 1, page_size: 100 });
    apps.value = response.data.data?.items || [];
    const next = selected.value
      ? apps.value.find((item) => item.id === selected.value?.id)
      : apps.value[0];
    if (next) await selectApp(next);
  } finally {
    loading.value = false;
  }
}
async function selectApp(app: ClientAppInfo) {
  selected.value = app;
  await Promise.all([loadReleases(), loadStaff()]);
}
async function loadReleases() {
  if (!selected.value?.id) return;
  releaseLoading.value = true;
  try {
    releases.value = (await ClientAppAPI.releases(selected.value.id)).data.data || [];
  } finally {
    releaseLoading.value = false;
  }
}
async function loadStaff() {
  if (!selected.value?.id) return;
  staffLoading.value = true;
  try {
    staffOptions.value = (await ClientAppAPI.staff(selected.value.id)).data.data || [];
    selectedStaffIds.value = staffOptions.value
      .filter((item) => item.selected)
      .map((item) => item.id);
  } finally {
    staffLoading.value = false;
  }
}
function openCreate() {
  editing.value = undefined;
  editorVisible.value = true;
}
function openEdit(app: ClientAppInfo) {
  editing.value = app;
  editorVisible.value = true;
}
async function save(form: ClientAppForm) {
  if (saving.value) return;
  if (editing.value && editing.value.service_mode !== form.service_mode) {
    try {
      await ElMessageBox.confirm(
        "改为均支持会保留用户当前模式。缩小服务范围前须处理不兼容权益和待处理订单，并下架不适用套餐；不会自动换算积分和天数。确认修改？",
        "修改服务模式",
        { type: "warning", confirmButtonText: "确认切换", cancelButtonText: "取消" }
      );
    } catch {
      return;
    }
  }
  if (editing.value?.status === "active" && form.status !== "active") {
    try {
      await ElMessageBox.confirm(
        `将“${editing.value.name}”设为${statusName(form.status || "draft")}后，用户将无法注册、登录或继续访问在线服务。是否继续？`,
        "确认停止运营",
        { type: "warning", confirmButtonText: "确认保存", cancelButtonText: "取消" }
      );
    } catch {
      return;
    }
  }
  saving.value = true;
  try {
    const response = editing.value?.id
      ? await ClientAppAPI.update(editing.value.id, form)
      : await ClientAppAPI.create(form as ClientAppForm & { code: string });
    const updated = response.data.data;
    clientAppStore.setContext(
      clientAppStore.apps.map((app) => (app.id === updated.id ? updated : app)),
      currentApp.value?.id === updated.id ? updated : currentApp.value
    );
    editorVisible.value = false;
    await loadApps();
  } catch (error) {
    // 请求层已提示业务失败，保留编辑内容，避免再报组件渲染异常。
    if (!(error instanceof HttpError)) throw error;
  } finally {
    saving.value = false;
  }
}
async function enterApp(app: ClientAppInfo) {
  if (app.id) await userStore.switchClientApp(app.id);
}
async function saveStaff() {
  if (!selected.value?.id || !selectedStaffIds.value.length)
    return ElMessage.warning("至少保留一名运营人员");
  staffSaving.value = true;
  try {
    await ClientAppAPI.setStaff(selected.value.id, selectedStaffIds.value);
    ElMessage.success("运营权限已保存");
    await loadStaff();
  } finally {
    staffSaving.value = false;
  }
}
function resetReleaseForm() {
  Object.assign(releaseForm, {
    version: "",
    channel: "test",
    release_notes: "",
    min_supported_version: "",
    force_update: false,
  });
  Object.assign(artifactForm, {
    external_url: "",
    file_name: "",
    file_size: 0,
    sha512: "",
    signature_verified: false,
  });
  artifactMode.value = "external";
  releaseFile.value = undefined;
  uploadProgress.value = 0;
}
function openRelease() {
  editingRelease.value = undefined;
  resetReleaseForm();
  releaseDialog.value = true;
}
function editRelease(item: ClientRelease) {
  editingRelease.value = item;
  Object.assign(releaseForm, {
    version: item.version,
    channel: item.channel,
    release_notes: item.release_notes,
    min_supported_version: item.min_supported_version || "",
    force_update: item.force_update,
  });
  const artifact = item.artifacts.find((entry) => entry.artifact_type === "installer");
  artifactMode.value = artifact?.source_type || "external";
  Object.assign(artifactForm, {
    external_url: artifact?.external_url || "",
    file_name: artifact?.file_name || "",
    file_size: artifact?.file_size || 0,
    sha512: artifact?.sha512 || "",
    signature_verified: artifact?.signature_verified || false,
  });
  releaseDialog.value = true;
}
function onReleaseFile(upload: UploadFile) {
  releaseFile.value = upload.raw;
  if (upload.raw) {
    artifactForm.file_name = upload.raw.name;
    artifactForm.file_size = upload.raw.size;
  }
}
async function saveRelease() {
  if (!selected.value?.id) return;
  if (!/^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$/.test(releaseForm.version))
    return ElMessage.warning("请输入正确的语义化版本号");
  releaseSaving.value = true;
  try {
    const appId = selected.value.id;
    let release = editingRelease.value;
    const wasEditing = Boolean(release?.id);
    if (!release?.id) {
      release = (
        await ClientAppAPI.createRelease(appId, {
          ...releaseForm,
          min_supported_version: releaseForm.min_supported_version || null,
        })
      ).data.data;
      if (!release) throw new Error("版本草稿创建失败");
    } else
      await ClientAppAPI.updateRelease(appId, release.id, {
        release_notes: releaseForm.release_notes,
        min_supported_version: releaseForm.min_supported_version || null,
        force_update: releaseForm.force_update,
      });
    if (!release.id) throw new Error("版本 ID 缺失");
    if (artifactMode.value === "external") {
      if (!artifactForm.external_url) return ElMessage.warning("请填写 HTTPS 安装包地址");
      await ClientAppAPI.saveExternalArtifact(appId, release.id, {
        artifact_type: "installer",
        ...artifactForm,
      });
    } else {
      if (!releaseFile.value) return ElMessage.warning("请选择安装包");
      const data = new FormData();
      data.append("artifact_type", "installer");
      data.append("file", releaseFile.value);
      data.append("sha512", artifactForm.sha512);
      data.append("signature_verified", String(artifactForm.signature_verified));
      await ClientAppAPI.uploadArtifact(
        appId,
        release.id,
        data,
        (percent) => (uploadProgress.value = percent)
      );
    }
    if (wasEditing) await ClientAppAPI.publishRelease(appId, release.id);
    ElMessage.success(wasEditing ? "版本已发布" : "版本草稿已创建");
    releaseDialog.value = false;
    await Promise.all([loadReleases(), loadApps()]);
  } finally {
    releaseSaving.value = false;
  }
}
async function withdraw(item: ClientRelease) {
  if (!selected.value?.id || !item.id) return;
  await ElMessageBox.confirm(`撤回 v${item.version} 后将停止继续分发，确认撤回？`, "撤回版本", {
    type: "warning",
  });
  await ClientAppAPI.withdrawRelease(selected.value.id, item.id);
  await loadReleases();
}
watch([editorVisible, releaseDialog], ([editor, release]) =>
  clientAppStore.markDirty("client-app-workspace", editor || release)
);
onMounted(loadApps);
onUnmounted(() => clientAppStore.markDirty("client-app-workspace", false));
</script>

<style scoped>
.client-workspace {
  display: grid;
  grid-template-columns: 300px minmax(0, 1fr);
  gap: 12px;
  min-height: 0;
  overflow: hidden;
}
.client-panel,
.detail-panel {
  min-height: 0;
  border: 1px solid var(--el-border-color-light);
  border-radius: 12px;
  background: var(--el-bg-color);
  box-shadow: var(--el-box-shadow-lighter);
}
.client-panel {
  display: flex;
  flex-direction: column;
  padding: 16px;
}
.client-search {
  display: flex;
  align-items: stretch;
  gap: 8px;
}
.client-search .el-input {
  flex: 1;
  min-width: 0;
}
.create-client-button {
  flex: 0 0 var(--el-component-size);
  width: var(--el-component-size);
  height: var(--el-component-size);
  padding: 0;
}
.section-tools,
.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.section-tools > div {
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.section-tools strong,
.card-head strong {
  font-size: 16px;
  color: var(--el-text-color-primary);
}
.section-tools span {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.status-filter {
  display: flex;
  gap: 4px;
  padding: 12px 0;
}
.status-filter button {
  border: 0;
  background: transparent;
  padding: 5px 9px;
  border-radius: 7px;
  color: var(--el-text-color-secondary);
  cursor: pointer;
}
.status-filter button.active {
  background: var(--el-color-primary-light-9);
  color: var(--el-color-primary);
  font-weight: 600;
}
.client-list {
  min-height: 0;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.client-item {
  display: grid;
  grid-template-columns: 42px minmax(0, 1fr) auto;
  gap: 10px;
  align-items: center;
  width: 100%;
  padding: 11px;
  border: 1px solid transparent;
  border-radius: 10px;
  background: transparent;
  text-align: left;
  cursor: pointer;
}
.client-item:hover {
  background: var(--el-fill-color-lighter);
}
.client-item.active {
  border-color: var(--el-color-primary-light-5);
  background: var(--el-color-primary-light-9);
}
.app-logo,
.hero-logo {
  display: grid;
  place-items: center;
  flex-shrink: 0;
  color: var(--el-color-primary);
}
.app-logo {
  width: 42px;
  height: 42px;
}
.app-logo img,
.hero-logo img {
  width: 100%;
  height: 100%;
  object-fit: contain;
}
.client-copy {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.client-copy strong,
.client-copy small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.client-copy strong {
  color: var(--el-text-color-primary);
}
.client-copy small {
  color: var(--el-text-color-secondary);
}
.client-item i {
  font-size: 11px;
  font-style: normal;
}
.status-active {
  color: var(--el-color-success);
}
.status-draft {
  color: var(--el-text-color-secondary);
}
.status-inactive {
  color: var(--el-color-danger);
}
.detail-panel {
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.detail-head {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 20px 22px;
  border-bottom: 1px solid var(--el-border-color-lighter);
}
.hero-logo {
  width: 62px;
  height: 62px;
  font-size: 22px;
}
.hero-copy {
  min-width: 0;
  flex: 1;
}
.hero-copy > div {
  display: flex;
  align-items: center;
  gap: 10px;
}
.hero-copy h2 {
  margin: 0;
  font-size: 20px;
}
.hero-copy p {
  margin: 7px 0;
  color: var(--el-text-color-regular);
}
.hero-copy > span {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.detail-tabs {
  min-height: 0;
  flex: 1;
  display: flex;
  flex-direction: column;
  padding: 0 22px;
}
:deep(.detail-tabs .el-tabs__content) {
  min-height: 0;
  flex: 1;
}
:deep(.detail-tabs .el-tab-pane) {
  height: 100%;
}
.tab-scroll {
  height: 100%;
  overflow: auto;
  padding: 6px 2px 22px;
}
.profile-layout {
  display: grid;
  grid-template-columns: 2fr 1fr;
  align-content: start;
  gap: 14px;
}
.info-card {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 12px;
  padding: 18px;
}
.info-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  margin: 12px 0 0;
}
.info-grid > div {
  padding: 14px 0;
  border-bottom: 1px solid var(--el-border-color-extra-light);
}
.info-grid dt {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.info-grid dd {
  margin: 7px 0 0;
  color: var(--el-text-color-primary);
  word-break: break-all;
}
.summary-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: 10px;
  margin-top: 14px;
}
.summary-grid div {
  padding: 13px;
  border-radius: 9px;
  background: var(--el-fill-color-lighter);
}
.summary-grid span {
  display: block;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.summary-grid strong {
  display: block;
  margin-top: 5px;
  font-size: 18px;
}
.section-tools {
  padding: 8px 0 16px;
}
.release-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.release-list article {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 16px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 11px;
}
.release-icon {
  display: grid;
  place-items: center;
  width: 44px;
  height: 44px;
  border-radius: 10px;
  background: var(--el-color-primary-light-9);
  color: var(--el-color-primary);
  font-size: 22px;
}
.release-main {
  min-width: 0;
  flex: 1;
}
.release-main > div {
  display: flex;
  align-items: center;
  gap: 7px;
}
.release-main p {
  margin: 7px 0;
  color: var(--el-text-color-regular);
}
.release-main span {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.staff-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}
.staff-grid :deep(.el-checkbox) {
  width: 100%;
  height: auto;
  margin: 0;
  padding: 14px;
}
.staff-grid :deep(.el-checkbox__label) {
  display: flex;
  align-items: center;
  gap: 9px;
}
.staff-grid :deep(.el-checkbox__label > span:last-child) {
  display: flex;
  flex-direction: column;
}
.staff-grid small {
  color: var(--el-text-color-secondary);
}
.staff-avatar {
  display: grid;
  place-items: center;
  width: 34px;
  height: 34px;
  border-radius: 50%;
  background: var(--el-color-primary-light-8);
  color: var(--el-color-primary);
}
.empty-detail {
  display: grid;
  place-items: center;
}
.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0 16px;
}
.form-tip {
  font-size: 12px;
  color: var(--el-color-warning);
  background: var(--el-color-warning-light-9);
  padding: 10px;
  border-radius: 8px;
}
.upload-progress {
  margin-top: 10px;
}
@media (width <= 1100px) {
  .client-workspace {
    grid-template-columns: 260px minmax(0, 1fr);
  }
  .profile-layout {
    grid-template-columns: 1fr;
  }
  .staff-grid {
    grid-template-columns: 1fr 1fr;
  }
}
@media (width <= 760px) {
  .client-workspace {
    display: block;
    overflow: auto;
  }
  .client-panel {
    min-height: 300px;
    margin-bottom: 12px;
  }
  .detail-panel {
    min-height: 650px;
  }
  .form-grid,
  .info-grid,
  .staff-grid {
    grid-template-columns: 1fr;
  }
}
</style>
