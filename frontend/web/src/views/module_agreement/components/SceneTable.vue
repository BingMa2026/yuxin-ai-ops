<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, ref, watch } from "vue";
import { ElMessageBox } from "element-plus";
import { onBeforeRouteLeave } from "vue-router";
import { renderTableOperationCell } from "@utils";
import API, { type Agreement, type AgreementScene, type SceneInput } from "@/api/module_agreement";
import FinanceSearchBar from "@/views/module_finance/components/FinanceSearchBar.vue";
import FaTableHeader from "@/components/tables/fa-table-header/index.vue";
import { useClientAppStore } from "@/store/modules/client-app.store";
import { useAgreementList } from "../use-agreement-list";
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
} = useAgreementList(API.scenes);
const store = useClientAppStore();
const open = ref(false),
  selected = ref<AgreementScene>(),
  busy = ref(false),
  optionsLoading = ref(false),
  optionsFailed = ref(false),
  options = ref<Agreement[]>([]);
const form = reactive<SceneInput>({
  code: "",
  name: "",
  agreement_ids: [],
  require_acceptance: true,
  revision: 0,
});
const original = ref("");
const dirty = computed(() => open.value && original.value !== JSON.stringify(form));
const required = computed(() =>
  ["auth", "membership_purchase", "credit_purchase"].includes(form.code)
);
const items = [
  {
    label: "使用场景",
    key: "keyword",
    type: "input" as const,
    props: { placeholder: "搜索场景名称或标识", clearable: true },
  },
];
const presets = [
  { code: "auth", name: "登录注册" },
  { code: "membership_purchase", name: "会员购买" },
  { code: "credit_purchase", name: "积分充值" },
  { code: "about", name: "关于页面" },
];
let alive = true,
  generation = 0;
async function loadOptions() {
  const scope = currentApp.value?.id,
    stamp = ++generation;
  if (!scope) {
    options.value = [];
    optionsLoading.value = false;
    optionsFailed.value = false;
    return;
  }
  optionsLoading.value = true;
  optionsFailed.value = false;
  try {
    const collected: Agreement[] = [];
    let page = 1,
      total = 0;
    do {
      const result = (await API.list({ page_no: page++, page_size: 100, status: "published" })).data
        .data;
      if (!alive || scope !== currentApp.value?.id || stamp !== generation) return;
      if (!result.items.length) break;
      collected.push(...result.items);
      total = result.total;
    } while (collected.length < total);
    if (alive && scope === currentApp.value?.id && stamp === generation) options.value = collected;
  } catch {
    if (alive && stamp === generation) optionsFailed.value = true;
  } finally {
    if (alive && stamp === generation) optionsLoading.value = false;
  }
}
function edit(row?: AgreementScene) {
  selected.value = row;
  Object.assign(
    form,
    row
      ? {
          code: row.code,
          name: row.name,
          agreement_ids: [...row.agreement_ids],
          require_acceptance: row.require_acceptance,
          revision: row.revision,
        }
      : { code: "", name: "", agreement_ids: [], require_acceptance: true, revision: 0 }
  );
  original.value = JSON.stringify(form);
  open.value = true;
  void loadOptions();
}
function preset(code: string) {
  const item = presets.find((p) => p.code === code);
  if (item) {
    form.code = item.code;
    form.name = item.name;
    form.require_acceptance = item.code !== "about";
  }
}
function move(index: number, delta: number) {
  const next = [...form.agreement_ids];
  const target = index + delta;
  if (target < 0 || target >= next.length) return;
  [next[index], next[target]] = [next[target]!, next[index]!];
  form.agreement_ids = next;
}
async function save() {
  if (busy.value || !currentApp.value || optionsFailed.value || optionsLoading.value) return;
  if (!/^[a-z][a-z0-9_]{1,63}$/.test(form.code) || !form.name.trim() || !form.agreement_ids.length)
    return;
  const scope = currentApp.value.id;
  const confirmed = await ElMessageBox.confirm(
    `保存后「${currentApp.value.name}」的「${form.name}」将立即使用所选协议和顺序。`,
    "保存场景配置",
    { confirmButtonText: "保存并生效", cancelButtonText: "取消" }
  )
    .then(() => true)
    .catch(() => false);
  if (!confirmed || scope !== currentApp.value?.id) return;
  busy.value = true;
  try {
    await API.saveScene(
      { ...form, require_acceptance: required.value || form.require_acceptance },
      selected.value?.id
    );
    if (alive && scope === currentApp.value?.id) {
      open.value = false;
      await load();
    }
  } catch {
    /* Request layer reports errors. */
  } finally {
    busy.value = false;
  }
}
async function remove(row: AgreementScene) {
  if (busy.value) return;
  const scope = currentApp.value?.id;
  const confirmed = await ElMessageBox.confirm(
    `删除「${currentApp.value?.name}」的「${row.name}」后，调用该场景将返回未配置。`,
    "删除场景",
    { type: "warning", confirmButtonText: "删除", cancelButtonText: "取消" }
  )
    .then(() => true)
    .catch(() => false);
  if (!confirmed || scope !== currentApp.value?.id) return;
  busy.value = true;
  try {
    await API.removeScene(row.id, row.revision);
    if (scope === currentApp.value?.id) await load();
  } catch {
    /* Request layer reports errors. */
  } finally {
    busy.value = false;
  }
}
async function canClose() {
  if (busy.value) return false;
  return (
    !dirty.value ||
    (await ElMessageBox.confirm("场景配置尚未保存，是否放弃修改？", "离开编辑", {
      confirmButtonText: "放弃修改",
      cancelButtonText: "继续编辑",
    })
      .then(() => true)
      .catch(() => false))
  );
}
async function close() {
  if (await canClose()) open.value = false;
}
onBeforeRouteLeave(canClose);
watch(dirty, (value) => store.markDirty("agreement-scene", value));
watch(rows, () => {
  void loadOptions();
});
watch(
  () => currentApp.value?.id,
  () => {
    open.value = false;
    options.value = [];
    void loadOptions();
  },
  { immediate: true }
);
onBeforeUnmount(() => {
  alive = false;
  generation++;
  store.markDirty("agreement-scene", false);
});
const { columns, columnChecks } = useTableColumns<AgreementScene>(() => [
  { prop: "name", label: "场景名称", minWidth: 120 },
  { prop: "code", label: "场景标识", minWidth: 180 },
  {
    prop: "agreement_ids",
    label: "关联协议（按展示顺序）",
    minWidth: 240,
    showOverflowTooltip: true,
    formatter: (r) =>
      r.agreement_ids
        .map((id) => options.value.find((a) => a.id === id)?.title || `协议 #${id}`)
        .join("、"),
  },
  {
    prop: "require_acceptance",
    label: "确认方式",
    width: 120,
    formatter: (r) => (r.require_acceptance ? "需要用户同意" : "仅供阅读"),
  },
  { prop: "updated_time", label: "更新时间", minWidth: 170 },
  {
    prop: "operation",
    label: "操作",
    width: 120,
    fixed: "right",
    formatter: (r) =>
      renderTableOperationCell([
        {
          key: "edit",
          label: "编辑",
          artType: "custom",
          icon: "ri:edit-line",
          perm: "workspace:user:agreement:scene",
          run: () => edit(r),
        },
        ...(!["auth", "membership_purchase", "credit_purchase"].includes(r.code)
          ? [
              {
                key: "delete",
                label: "删除",
                artType: "custom" as const,
                icon: "ri:delete-bin-line",
                perm: "workspace:user:agreement:delete",
                run: () => void remove(r),
              },
            ]
          : []),
      ]),
  },
]);
</script>
<template>
  <section class="fa-full-height">
    <template v-if="currentApp"
      ><FinanceSearchBar
        v-show="showSearchBar"
        v-model="query"
        :items="items"
        :show-expand="false"
        @search="search"
        @reset="reset"
      />
      <ElCard class="fa-table-card" :style="{ marginTop: showSearchBar ? '12px' : '0' }"
        ><FaTableHeader
          v-model:columns="columnChecks"
          v-model:showSearchBar="showSearchBar"
          :loading="loading"
          @refresh="load"
          ><template #left
            ><ElButton v-hasPerm="['workspace:user:agreement:scene']" type="primary" @click="edit()"
              ><FaSvgIcon icon="ri:add-line" />新增场景</ElButton
            ></template
          ></FaTableHeader
        ><ElAlert
          v-if="failed"
          title="场景加载失败，请刷新重试"
          type="error"
          :closable="false" /><FaTable
          :loading="loading"
          :data="rows"
          :columns="columns"
          :pagination="pagination"
          @pagination:current-change="changePage"
          @pagination:size-change="changeSize"
      /></ElCard> </template
    ><ElCard v-else><ElEmpty description="请先选择客户端" /></ElCard>
    <ElDrawer
      v-model="open"
      :title="selected ? '编辑使用场景' : '新增使用场景'"
      size="min(620px, 100vw)"
      :before-close="close"
      :close-on-click-modal="false"
    >
      <ElForm label-position="top" :disabled="busy">
        <ElFormItem v-if="!selected" label="常用场景"
          ><ElSelect placeholder="选择常用场景，也可自行填写" @change="preset"
            ><ElOption
              v-for="item in presets"
              :key="item.code"
              :value="item.code"
              :label="item.name" /></ElSelect
        ></ElFormItem>
        <ElFormItem label="场景名称" required
          ><ElInput v-model="form.name" maxlength="120"
        /></ElFormItem>
        <ElFormItem label="场景标识" required
          ><ElInput
            v-model="form.code"
            :disabled="Boolean(selected)"
            placeholder="例如：membership_purchase"
            maxlength="64"
          /><small
            >客户端通过此标识获取协议。新增场景需要客户端接入，已有标识不能修改。</small
          ></ElFormItem
        >
        <ElFormItem label="关联协议" required
          ><ElSelect
            v-model="form.agreement_ids"
            multiple
            filterable
            :loading="optionsLoading"
            placeholder="选择当前客户端已发布的协议"
            style="width: 100%"
            ><ElOption
              v-for="agreement in options"
              :key="agreement.id"
              :value="agreement.id"
              :label="`${agreement.title}（${agreement.code}）`" /></ElSelect
        ></ElFormItem>
        <ElAlert
          v-if="optionsFailed"
          type="error"
          title="协议选项加载失败，无法保存"
          :closable="false"
          ><ElButton @click="loadOptions">重新加载</ElButton></ElAlert
        >
        <div v-for="(id, index) in form.agreement_ids" :key="id" class="scene-order">
          <span
            >{{ index + 1 }}. {{ options.find((a) => a.id === id)?.title || `协议 #${id}` }}</span
          ><ElButton :disabled="index === 0" aria-label="上移" @click="move(index, -1)"
            >上移</ElButton
          ><ElButton
            :disabled="index === form.agreement_ids.length - 1"
            aria-label="下移"
            @click="move(index, 1)"
            >下移</ElButton
          >
        </div>
        <ElFormItem label="确认方式"
          ><ElSwitch
            v-model="form.require_acceptance"
            :disabled="required"
            active-text="需要用户同意"
            inactive-text="仅供阅读"
        /></ElFormItem>
        <p v-if="required" class="scene-note">
          注册和购买场景需要用户明确同意，服务端会校验提交的协议版本。
        </p>
      </ElForm>
      <template #footer
        ><ElButton @click="close">取消</ElButton
        ><ElButton
          type="primary"
          :loading="busy"
          :disabled="
            optionsLoading ||
            optionsFailed ||
            !form.name.trim() ||
            !/^[a-z][a-z0-9_]{1,63}$/.test(form.code) ||
            !form.agreement_ids.length
          "
          @click="save"
          >保存并生效</ElButton
        ></template
      >
    </ElDrawer>
  </section>
</template>
<style scoped>
.scene-order {
  display: flex;
  align-items: center;
  margin-bottom: 12px;
  gap: 8px;
}
.scene-order span {
  flex: 1;
}
small,
.scene-note {
  color: var(--el-text-color-secondary);
  font-size: 13px;
}
</style>
