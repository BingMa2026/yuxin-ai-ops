<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
import { ElMessageBox } from "element-plus";
import { onBeforeRouteLeave } from "vue-router";
import API, {
  type Agreement,
  type AgreementVersion,
  type DraftInput,
} from "@/api/module_agreement";
import { useClientAppStore } from "@/store/modules/client-app.store";
import FaWangEditor from "@/components/forms/fa-wang-editor/index.vue";
import AgreementContent from "./AgreementContent.vue";

const props = defineProps<{ id?: number; readOnly: boolean; appId: number; appName: string }>();
const emit = defineEmits<{ close: []; saved: [] }>();
const store = useClientAppStore();
const row = ref<Agreement>(),
  versions = ref<AgreementVersion[]>([]),
  selectedVersion = ref<number>();
const loading = ref(true),
  failed = ref(false),
  saving = ref(false),
  publishing = ref(false),
  saveFailed = ref(false);
const tab = ref(props.readOnly ? "preview" : "edit"),
  ready = ref(false),
  savedAt = ref("");
const form = reactive<DraftInput>({
  code: "",
  title: "",
  content: "",
  change_summary: "",
  revision: 0,
});
const savedSnapshot = ref("");
const source = `agreement-editor-${props.appId}`;
let alive = true,
  timer: ReturnType<typeof setTimeout> | undefined;
const snapshot = () =>
  JSON.stringify({
    code: form.code,
    title: form.title,
    content: form.content,
    change_summary: form.change_summary,
  });
const dirty = computed(() => ready.value && snapshot() !== savedSnapshot.value);
const currentVersion = computed(() =>
  versions.value.find((v) => v.version === row.value?.current_version)
);
const historical = computed(() => versions.value.find((v) => v.id === selectedVersion.value));
const preview = computed(() =>
  props.readOnly && currentVersion.value ? currentVersion.value : form
);
const saveLabel = computed(() =>
  saving.value
    ? "正在保存…"
    : saveFailed.value
      ? "保存失败，当前输入已保留，请重试"
      : dirty.value
        ? "有未保存修改"
        : savedAt.value
          ? `已保存于 ${savedAt.value}`
          : "草稿自动保存"
);
const toolbar = [
  "headerSelect",
  "bold",
  "italic",
  "underline",
  "bulletedList",
  "numberedList",
  "insertLink",
  "insertTable",
  "clearStyle",
  "undo",
  "redo",
];
function inScope() {
  return alive && props.appId === store.currentApp?.id;
}
function apply(next: Agreement) {
  row.value = next;
  Object.assign(form, {
    code: next.code,
    title: next.title,
    content: next.content,
    change_summary: next.change_summary,
    revision: next.revision,
  });
  savedSnapshot.value = snapshot();
}
async function load() {
  loading.value = true;
  failed.value = false;
  ready.value = false;
  try {
    if (props.id) {
      const [detail, history] = await Promise.all([API.detail(props.id), API.versions(props.id)]);
      if (!inScope()) return;
      apply(detail.data.data);
      versions.value = history.data.data;
      selectedVersion.value = versions.value[0]?.id;
    } else savedSnapshot.value = snapshot();
    ready.value = true;
  } catch {
    if (inScope()) failed.value = true;
  } finally {
    if (inScope()) loading.value = false;
  }
}
async function save(): Promise<boolean> {
  if (saving.value || !inScope() || props.readOnly) return false;
  if (!dirty.value && row.value) return true;
  if (!/^[a-z][a-z0-9_]{1,63}$/.test(form.code) || !form.title.trim()) {
    saveFailed.value = true;
    return false;
  }
  clearTimeout(timer);
  saving.value = true;
  saveFailed.value = false;
  const captured = snapshot();
  try {
    const next = (await API.save({ ...form }, row.value?.id)).data.data;
    if (!inScope()) return false;
    row.value = next;
    form.revision = next.revision;
    // A response must not overwrite keystrokes typed while saving.
    if (snapshot() === captured) {
      form.content = next.content;
      savedSnapshot.value = snapshot();
    } else savedSnapshot.value = captured;
    savedAt.value = new Date().toLocaleTimeString("zh-CN", { hour12: false });
    emit("saved");
    return !dirty.value;
  } catch {
    if (inScope()) saveFailed.value = true;
    return false;
  } finally {
    if (inScope()) {
      saving.value = false;
      if (dirty.value && !saveFailed.value) schedule();
    }
  }
}
function schedule() {
  clearTimeout(timer);
  if (!ready.value || props.readOnly || saveFailed.value || publishing.value) return;
  timer = setTimeout(() => {
    if (dirty.value && form.title.trim() && /^[a-z][a-z0-9_]{1,63}$/.test(form.code)) void save();
  }, 1500);
}
watch(() => [form.code, form.title, form.content, form.change_summary], schedule);
watch(dirty, (value) => store.markDirty(source, value));
async function canClose() {
  if (saving.value || publishing.value) return false;
  if (!dirty.value) return true;
  return ElMessageBox.confirm("当前内容尚未保存，离开将丢失这些修改。", "离开编辑", {
    confirmButtonText: "放弃修改",
    cancelButtonText: "继续编辑",
    type: "warning",
  })
    .then(() => true)
    .catch(() => false);
}
async function close() {
  if (await canClose()) emit("close");
}
onBeforeRouteLeave(canClose);
function beforeUnload(event: BeforeUnloadEvent) {
  if (dirty.value) {
    event.preventDefault();
    event.returnValue = "";
  }
}
async function publish() {
  if (publishing.value || saving.value || !form.change_summary.trim()) return;
  if ((!props.readOnly && !(await save())) || !row.value) return;
  clearTimeout(timer);
  const revision = row.value.revision;
  const confirmed = await ElMessageBox.confirm(
    `将向「${props.appName}」发布《${form.title}》V${row.value.current_version + 1}，立即生效。使用该协议的场景将读取新版本。`,
    "发布协议",
    { type: "warning", confirmButtonText: "确认发布", cancelButtonText: "取消" }
  )
    .then(() => true)
    .catch(() => false);
  if (!confirmed || !inScope() || dirty.value || revision !== row.value.revision) return;
  publishing.value = true;
  try {
    const next = (await API.publish(row.value.id, revision)).data.data;
    if (!inScope()) return;
    apply(next);
    const history = (await API.versions(next.id)).data.data;
    if (!inScope()) return;
    versions.value = history;
    tab.value = "preview";
    emit("saved");
  } catch {
    /* Request layer reports errors. */
  } finally {
    publishing.value = false;
  }
}
async function restore() {
  if (!row.value || !historical.value || publishing.value || saving.value) return;
  const confirmed = await ElMessageBox.confirm(
    `将 V${historical.value.version} 复制为新草稿，替换现有草稿内容。`,
    "恢复历史内容",
    { confirmButtonText: "复制为草稿", cancelButtonText: "取消" }
  )
    .then(() => true)
    .catch(() => false);
  if (!confirmed || !inScope()) return;
  clearTimeout(timer);
  publishing.value = true;
  try {
    const next = (await API.restore(row.value.id, historical.value.id, row.value.revision)).data
      .data;
    if (!inScope()) return;
    apply(next);
    tab.value = "edit";
    emit("saved");
  } catch {
    /* Request layer reports errors. */
  } finally {
    publishing.value = false;
  }
}
onMounted(() => {
  window.addEventListener("beforeunload", beforeUnload);
  void load();
});
onBeforeUnmount(() => {
  alive = false;
  clearTimeout(timer);
  store.markDirty(source, false);
  window.removeEventListener("beforeunload", beforeUnload);
});
</script>
<template>
  <ElDialog
    :model-value="true"
    fullscreen
    :before-close="close"
    :close-on-click-modal="false"
    class="agreement-editor"
  >
    <template #header
      ><div class="editor-header">
        <strong>{{ readOnly ? "查看协议" : row ? "编辑协议" : "新增协议" }}</strong
        ><span>{{ appName }}</span
        ><span v-if="!readOnly" role="status">{{ saveLabel }}</span>
      </div></template
    >
    <div v-loading="loading">
      <ElAlert v-if="failed" title="协议加载失败" type="error" :closable="false"
        ><ElButton @click="load">重新加载</ElButton></ElAlert
      >
      <template v-else-if="ready">
        <ElTabs v-model="tab"
          ><ElTabPane v-if="!readOnly" label="编辑草稿" name="edit" /><ElTabPane
            :label="readOnly ? '当前生效内容' : '客户端预览'"
            name="preview" /><ElTabPane label="历史版本" name="history" /><ElTabPane
            v-if="readOnly && row?.has_draft"
            label="待发布草稿"
            name="draft" /><ElTabPane
            v-if="currentVersion && !readOnly"
            label="与当前版本对照"
            name="compare"
        /></ElTabs>
        <div v-if="tab === 'edit'" class="editor-layout">
          <section class="editor-main" :inert="publishing">
            <FaWangEditor
              v-model="form.content"
              height="calc(100vh - 285px)"
              :toolbar-keys="toolbar"
              placeholder="输入协议正文，支持粘贴已有文档内容"
            />
          </section>
          <ElForm class="editor-meta" label-position="top" :disabled="publishing">
            <ElFormItem label="协议名称" required
              ><ElInput v-model="form.title" maxlength="120" placeholder="例如：用户协议"
            /></ElFormItem>
            <ElFormItem label="协议标识" required
              ><ElInput
                v-model="form.code"
                :disabled="Boolean(row?.current_version)"
                maxlength="64"
                placeholder="例如：user_agreement"
              /><small>2–64 位小写字母、数字和下划线，字母开头；发布后固定。</small></ElFormItem
            >
            <ElFormItem label="更新说明（发布必填）"
              ><ElInput
                v-model="form.change_summary"
                type="textarea"
                :rows="5"
                maxlength="1000"
                show-word-limit
                placeholder="简要说明本次更新内容"
            /></ElFormItem>
            <ElAlert
              v-if="saveFailed"
              title="保存未完成，请保留输入后重试。发生版本冲突时可先复制正文，再重新打开。"
              type="warning"
              :closable="false"
            />
            <p v-if="row?.current_version">
              当前线上版本：V{{ row.current_version }}。保存草稿不会更新线上正文。
            </p>
          </ElForm>
        </div>
        <section v-else-if="tab === 'draft'">
          <p>更新说明：{{ form.change_summary || "尚未填写，暂不能发布" }}</p>
          <AgreementContent :title="form.title" :content="form.content" />
        </section>
        <AgreementContent
          v-else-if="tab === 'preview'"
          :title="preview.title"
          :content="preview.content"
        />
        <div v-else-if="tab === 'compare' && currentVersion" class="comparison">
          <section>
            <h3>当前生效 · V{{ currentVersion.version }}</h3>
            <AgreementContent :title="currentVersion.title" :content="currentVersion.content" />
          </section>
          <section>
            <h3>本次草稿</h3>
            <AgreementContent :title="form.title" :content="form.content" />
          </section>
        </div>
        <section v-else-if="tab === 'history'">
          <ElEmpty v-if="!versions.length" description="尚无发布版本" />
          <template v-else
            ><div class="version-toolbar">
              <ElSelect v-model="selectedVersion" style="width: 330px"
                ><ElOption
                  v-for="version in versions"
                  :key="version.id"
                  :value="version.id"
                  :label="`V${version.version} · ${version.published_at}`" /></ElSelect
              ><ElButton
                v-if="!readOnly && row?.status !== 'archived'"
                v-hasPerm="['workspace:user:agreement:update']"
                :disabled="saving || publishing"
                @click="restore"
                >复制为新草稿</ElButton
              >
            </div>
            <p>{{ historical?.change_summary }}</p>
            <AgreementContent
              v-if="historical"
              :title="historical.title"
              :content="historical.content"
          /></template>
        </section>
      </template>
    </div>
    <template #footer
      ><ElButton @click="close">关闭</ElButton
      ><template v-if="!readOnly && ready"
        ><ElButton :loading="saving" :disabled="publishing" @click="save">保存草稿</ElButton
        ><ElButton @click="tab = 'preview'">客户端预览</ElButton></template
      ><ElButton
        v-if="ready && row?.status !== 'archived' && (!readOnly || tab === 'draft')"
        v-hasPerm="['workspace:user:agreement:publish']"
        type="primary"
        :loading="publishing"
        :disabled="saving || !form.change_summary.trim() || (!dirty && !row?.has_draft)"
        @click="publish"
        >发布</ElButton
      ></template
    >
  </ElDialog>
</template>
<style scoped>
:global(.agreement-editor) {
  display: flex;
  flex-direction: column;
}
:global(.agreement-editor > .el-dialog__body) {
  flex: 1;
  min-height: 0;
  overflow: auto;
}
.editor-header,
.version-toolbar {
  display: flex;
  align-items: center;
  gap: 20px;
}
.editor-header span,
small,
.editor-meta p {
  color: var(--el-text-color-secondary);
  font-size: 13px;
}
.editor-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 300px;
  gap: 28px;
}
.editor-main {
  min-width: 0;
}
.editor-meta {
  border-left: 1px solid var(--el-border-color);
  padding-left: 24px;
}
.comparison {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 24px;
}
.comparison section {
  min-width: 0;
  border: 1px solid var(--el-border-color);
}
.comparison h3 {
  padding: 12px 24px;
  background: var(--el-fill-color-light);
}
@media (max-width: 850px) {
  .editor-layout,
  .comparison {
    grid-template-columns: 1fr;
  }
  .editor-meta {
    grid-row: 1;
    border: 0;
    padding: 0;
  }
  .editor-header {
    flex-wrap: wrap;
    gap: 8px;
  }
}
</style>
