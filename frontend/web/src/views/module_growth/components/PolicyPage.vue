<script setup lang="ts">
import { computed, h, reactive, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { ElButton, ElMessageBox } from "element-plus";
import { useClientAppStore } from "@stores";
import GrowthAPI, {
  type GrowthRule,
  type RuleKind,
  type GradePolicy,
  type RightsPolicy,
  type IncentivePolicy,
  type Evaluation,
  metricLabels,
  eventLabels,
} from "@/api/module_growth";
import GradeEditor from "./GradeEditor.vue";
import RightsEditor from "./RightsEditor.vue";
import IncentiveEditor from "./IncentiveEditor.vue";
import type { SearchFormItem } from "@/components/forms/fa-search-bar/index.vue";
import FaTableHeader from "@/components/tables/fa-table-header/index.vue";
import { renderTableOperationCell } from "@utils";
import AuditPanel from "./AuditPanel.vue";
import type { ColumnOption } from "@/types/component";
import RuleTag from "./RuleTag.vue";
import RuleDetails from "./RuleDetails.vue";
import PolicyPresentation from "./PolicyPresentation.vue";
const presentationVisible = ref(false);
const presentationRule = ref<GrowthRule | null>(null);
const presentationUnsaved = ref(false);
function showPresentation(rule: GrowthRule, unsaved = false) {
  presentationRule.value = numericConfig(rule);
  presentationUnsaved.value = unsaved;
  presentationVisible.value = true;
}
const detail = ref<GrowthRule | null>(null);
const detailVisible = ref(false);
function showDetail(rule: GrowthRule) {
  if (rule.kind !== "incentive") {
    showPresentation(rule);
    return;
  }
  detail.value = rule;
  detailVisible.value = true;
}
const legacy = ref<{ id: number; name: string; type: string }[]>([]);
const metricName = (key: string) =>
  (metricLabels as Record<string, string>)[key] ||
  (
    { retention_samples: "留存成熟样本数", compliance_coverage: "合规核验覆盖率（%）" } as Record<
      string,
      string
    >
  )[key] ||
  key;
const props = defineProps<{ kind: RuleKind }>();
const { currentApp } = storeToRefs(useClientAppStore());
const titles: Record<RuleKind, string> = {
  usage: "用户等级",
  promotion: "推广等级",
  rights: "权益管理",
  incentive: "激励规则",
};
const rows = ref<GrowthRule[]>([]),
  loading = ref(false),
  busy = ref(false),
  failed = ref(false),
  tab = ref("rules");
const auditKind = computed(() => tab.value as "rewards" | "tasks" | "events");
const keyword = ref(""),
  state = ref(""),
  history = ref(false),
  editor = ref<GrowthRule | null>(null),
  editorVisible = ref(false);
const detailBudget = computed(() =>
  rows.value
    .filter((r) => r.key === detail.value?.key)
    .reduce(
      (total, r) => ({
        credits: total.credits + r.used_credits,
        cash: total.cash + r.used_cash_fen,
      }),
      { credits: 0, cash: 0 }
    )
);
const previewVisible = ref(false),
  previewLoading = ref(false),
  previews = ref<Evaluation[]>([]),
  previewId = ref(0),
  previewPage = ref(1),
  previewTotal = ref(0);
const publishTarget = ref<GrowthRule | null>(null),
  effectiveAt = ref("");
const statusLabels = { draft: "待发布", published: "已发布", stopped: "已停用" };
const latest = computed(() =>
  rows.value.filter((r, i, all) => all.findIndex((x) => x.key === r.key) === i)
);
const filtered = computed(() =>
  (history.value ? rows.value : latest.value).filter(
    (r) =>
      (!keyword.value || r.name.includes(keyword.value) || r.key.includes(keyword.value)) &&
      (!state.value || r.status === state.value)
  )
);
const query = reactive({ keyword: "", state: "" }),
  showSearchBar = ref(true),
  pageNo = ref(1),
  pageSize = ref(10);
const searchItems: SearchFormItem[] = [
  {
    label: "规则搜索",
    key: "keyword",
    type: "input",
    props: { clearable: true, placeholder: "规则名称 / 编号" },
    span: 8,
  },
  {
    label: "状态",
    key: "state",
    type: "select",
    props: {
      clearable: true,
      options: Object.entries(statusLabels).map(([value, label]) => ({ value, label })),
    },
    span: 8,
  },
];
function search() {
  keyword.value = query.keyword;
  state.value = query.state;
  pageNo.value = 1;
}
function reset() {
  query.keyword = "";
  query.state = "";
  search();
}
const pageRows = computed(() =>
  filtered.value.slice((pageNo.value - 1) * pageSize.value, pageNo.value * pageSize.value)
);
const pagination = computed(() => ({
  current: pageNo.value,
  size: pageSize.value,
  total: filtered.value.length,
}));
function summaryColumns(): ColumnOption<GrowthRule>[] {
  if (props.kind === "usage" || props.kind === "promotion")
    return [
      {
        prop: "grades",
        label: "等级范围",
        minWidth: 130,
        formatter: (r) =>
          h(
            "div",
            { class: "growth-tag-group" },
            (r.config as GradePolicy).grades.map((g) => h(RuleTag, { value: g.code }))
          ),
      },
      {
        prop: "window",
        label: "统计窗口",
        width: 100,
        formatter: (r) => `${(r.config as GradePolicy).window_days} 天`,
      },
      {
        prop: "cadence",
        label: "评估周期",
        width: 100,
        formatter: (r) =>
          ({ daily: "每日", weekly: "每周", monthly: "每月" })[(r.config as GradePolicy).cadence],
      },
    ];
  if (props.kind === "rights")
    return [
      {
        prop: "validity",
        label: "积分有效期",
        width: 120,
        formatter: (r) => `${(r.config as RightsPolicy).credit_valid_days} 天`,
      },
      {
        prop: "gift",
        label: "积分转赠",
        width: 100,
        formatter: (r) =>
          h(RuleTag, { value: (r.config as RightsPolicy).gift_enabled ? "enabled" : "disabled" }),
      },
      {
        prop: "withdrawal",
        label: "现金提现",
        width: 100,
        formatter: (r) =>
          h(RuleTag, {
            value: (r.config as RightsPolicy).withdrawal_enabled ? "enabled" : "disabled",
          }),
      },
    ];
  return [
    {
      prop: "event",
      label: "触发事件",
      minWidth: 140,
      formatter: (r) => eventLabels[(r.config as IncentivePolicy).event],
    },
    {
      prop: "rewards",
      label: "奖励内容",
      minWidth: 220,
      formatter: (r) =>
        (r.config as IncentivePolicy).actions
          .map(
            (a) =>
              `${a.recipient === "actor" ? "本人" : "邀请人"} · ${a.calculation === "paid_percent" ? `${a.percent}%（基础）` : a.asset === "cash" ? `¥${(a.amount / 100).toFixed(2)}` : `${a.amount} 积分`}`
          )
          .join("；"),
    },
    {
      prop: "mode",
      label: "发放方式",
      width: 120,
      formatter: (r) =>
        h(RuleTag, {
          value: (r.config as IncentivePolicy).mode,
          label: (r.config as IncentivePolicy).mode === "review" ? "审核后发放" : undefined,
        }),
    },
  ];
}
const { columnChecks, columns } = useTableColumns<GrowthRule>(() => [
  { type: "globalIndex", width: 56, label: "序号" },
  { prop: "name", label: "规则名称", minWidth: 150 },
  {
    prop: "key",
    label: "规则编号",
    minWidth: 150,
    formatter: (r) =>
      h(ElButton, { link: true, type: "primary", onClick: () => showDetail(r) }, () => r.key),
  },
  ...summaryColumns(),
  { prop: "version", label: "版本", width: 80, formatter: (r) => `V${r.version}` },
  {
    prop: "status",
    label: "状态",
    width: 100,
    formatter: (r) =>
      h(RuleTag, {
        value: r.status,
        scheduled:
          r.status === "published" && !!r.effective_at && new Date(r.effective_at) > new Date(),
      }),
  },
  {
    prop: "effective_at",
    label: "生效时间",
    minWidth: 150,
    formatter: (r) => (r.effective_at ? new Date(r.effective_at).toLocaleString() : "尚未发布"),
  },
  {
    prop: "operation",
    label: "操作",
    width: 140,
    fixed: "right",
    align: "center",
    formatter: (r) =>
      renderTableOperationCell([
        ...(props.kind !== "incentive"
          ? [
              {
                key: "presentation",
                label: "预览",
                artType: "custom" as const,
                icon: "ri:eye-line",
                run: () => showPresentation(r),
              },
            ]
          : []),
        {
          key: "edit",
          label: "配置",
          artType: "custom",
          icon: "ri:settings-3-line",
          perm: "workspace:rule:manage",
          run: () => edit(r),
        },
        ...(props.kind === "usage" || props.kind === "promotion"
          ? [
              {
                key: "preview",
                label: "计算预览",
                artType: "custom" as const,
                icon: "ri:calculator-line",
                run: () => void preview(r),
              },
            ]
          : []),
        ...(r.status === "draft"
          ? [
              {
                key: "publish",
                label: "发布",
                artType: "custom" as const,
                icon: "ri:send-plane-line",
                perm: "workspace:rule:manage",
                run: () => {
                  publishTarget.value = r;
                  effectiveAt.value = new Date().toISOString();
                },
              },
            ]
          : []),
        ...(r.status === "published"
          ? [
              {
                key: "stop",
                label: "停用",
                artType: "custom" as const,
                icon: "ri:stop-circle-line",
                perm: "workspace:rule:manage",
                run: () => void stop(r),
              },
            ]
          : []),
      ]),
  },
]);
let loadGeneration = 0;
function numericConfig(rule: GrowthRule): GrowthRule {
  const copy = JSON.parse(JSON.stringify(rule)) as GrowthRule;
  if (copy.kind === "usage" || copy.kind === "promotion") {
    const c = copy.config as GradePolicy;
    c.dimensions.forEach((d) => {
      d.cap = Number(d.cap);
    });
    c.grades.forEach((g) => {
      g.min_score = Number(g.min_score);
      g.conditions.forEach((c) => {
        c.value = Number(c.value);
      });
    });
  } else if (copy.kind === "incentive") {
    (copy.config as IncentivePolicy).actions.forEach((a) => {
      a.percent = Number(a.percent);
      Object.keys(a.grade_percent).forEach((k) => {
        a.grade_percent[k] = Number(a.grade_percent[k]);
      });
    });
  }
  return copy;
}
async function load() {
  const generation = ++loadGeneration;
  if (!currentApp.value) {
    rows.value = [];
    legacy.value = [];
    loading.value = false;
    return;
  }
  loading.value = true;
  failed.value = false;
  try {
    const [rules, refs] = await Promise.all([
      GrowthAPI.rules(props.kind),
      props.kind === "usage" ? GrowthAPI.legacy() : Promise.resolve(null),
    ]);
    if (generation === loadGeneration) {
      rows.value = rules.data.data;
      legacy.value = refs?.data.data || [];
    }
  } catch {
    if (generation === loadGeneration) {
      failed.value = true;
      rows.value = [];
    }
  } finally {
    if (generation === loadGeneration) loading.value = false;
  }
}
async function archiveLegacy(id: number) {
  if (
    !(await ElMessageBox.confirm(
      "归档后该旧LV分群停止使用，历史记录保留。请先在用户管理中按R/A等级建立新分群。",
      "归档旧分群",
      { type: "warning" }
    )
      .then(() => true)
      .catch(() => false))
  )
    return;
  busy.value = true;
  try {
    await GrowthAPI.archiveLegacy(id);
    await load();
  } finally {
    busy.value = false;
  }
}
async function seed() {
  busy.value = true;
  try {
    await GrowthAPI.seed();
    await load();
  } finally {
    busy.value = false;
  }
}
function edit(rule: GrowthRule) {
  presentationVisible.value = false;
  detailVisible.value = false;
  editor.value = numericConfig(rule);
  editorVisible.value = true;
}
function create() {
  editor.value = {
    id: 0,
    key: "",
    kind: "incentive",
    name: "",
    version: 0,
    status: "draft",
    created_time: "",
    effective_at: null,
    used_credits: 0,
    used_cash_fen: 0,
    config: {
      event: "artifact",
      name: "",
      description: "",
      mode: "review",
      feedback_grade: null,
      usage_grades: [],
      promotion_grades: [],
      require_subscription: false,
      priority: 100,
      stackable: false,
      daily_limit: 3,
      monthly_limit: 30,
      observe_days: 0,
      budget_credits: 0,
      budget_cash_fen: 0,
      actions: [
        {
          recipient: "actor",
          asset: "credits",
          calculation: "fixed",
          amount: 100,
          percent: 0,
          grade_percent: {},
          credits_per_yuan: 100,
          maximum: 100000,
        },
      ],
    },
  };
  editorVisible.value = true;
}
const saveProblem = computed(() => {
  if (!editor.value) return "";
  if (!editor.value.name.trim()) return "请填写规则名称";
  if (!/^[a-z][a-z0-9_-]*$/.test(editor.value.key))
    return "规则编号请以小写字母开头，仅使用小写字母、数字、下划线或连字符";
  if (editor.value.kind === "usage") {
    if (legacy.value.length) return "请先迁移旧 LV 等级引用";
    if (
      (editor.value.config as GradePolicy).dimensions.reduce((sum, d) => sum + d.weight, 0) !== 100
    )
      return "评分权重合计需为 100%";
  }
  if (editor.value.kind === "incentive") {
    const c = editor.value.config as IncentivePolicy;
    if (c.mode !== "simulation") {
      if (c.actions.some((a) => a.asset === "credits") && !(c.budget_credits > 0))
        return "正式发放积分前，请设置大于 0 的积分总预算";
      if (c.actions.some((a) => a.asset === "cash") && !(c.budget_cash_fen > 0))
        return "正式发放现金前，请设置大于 0 的现金总预算";
    }
  }
  return "";
});
async function save() {
  if (!editor.value || saveProblem.value) return;
  busy.value = true;
  try {
    const { kind, key, name, config } = editor.value;
    if (kind === "incentive") (config as IncentivePolicy).name = name;
    await GrowthAPI.saveAndPublish({ kind, key, name, config });
    editorVisible.value = false;
    await load();
  } finally {
    busy.value = false;
  }
}
async function publish() {
  if (!publishTarget.value || !effectiveAt.value) return;
  busy.value = true;
  try {
    await GrowthAPI.publish(publishTarget.value.id, new Date(effectiveAt.value).toISOString());
    publishTarget.value = null;
    await load();
  } finally {
    busy.value = false;
  }
}
async function stop(rule: GrowthRule) {
  if (
    !(await ElMessageBox.confirm(
      `停用“${rule.name}”后不再接收新奖励，已生成的奖励单继续处理。`,
      "停用规则",
      { type: "warning" }
    )
      .then(() => true)
      .catch(() => false))
  )
    return;
  busy.value = true;
  try {
    await GrowthAPI.stop(rule.id);
    await load();
  } finally {
    busy.value = false;
  }
}
async function preview(rule?: GrowthRule) {
  if (rule) {
    previewId.value = rule.id;
    previewPage.value = 1;
    previewVisible.value = true;
  }
  previewLoading.value = true;
  const generation = loadGeneration;
  const id = previewId.value;
  const page = previewPage.value;
  try {
    const data = (await GrowthAPI.preview(id, page)).data.data;
    if (generation === loadGeneration && id === previewId.value && page === previewPage.value) {
      previews.value = data.items;
      previewTotal.value = data.total;
    }
  } finally {
    if (generation === loadGeneration && id === previewId.value && page === previewPage.value)
      previewLoading.value = false;
  }
}
watch(
  () => [currentApp.value?.id, props.kind],
  () => {
    editorVisible.value = false;
    detailVisible.value = false;
    presentationVisible.value = false;
    presentationRule.value = null;
    pageNo.value = 1;
    previewVisible.value = false;
    previews.value = [];
    previewLoading.value = false;
    publishTarget.value = null;
    rows.value = [];
    tab.value = "rules";
    void load();
  },
  { immediate: true }
);
</script>
<template>
  <main class="growth-page fa-full-height">
    <ElCard v-if="!currentApp" class="fa-table-card"
      ><ElEmpty description="请先在顶栏选择客户端"
    /></ElCard>
    <template v-else>
      <ElTabs v-if="kind === 'incentive'" v-model="tab" class="growth-tabs">
        <ElTabPane label="规则配置" name="rules" />
        <ElTabPane label="奖励记录" name="rewards" />
        <ElTabPane label="任务核验" name="tasks" />
        <ElTabPane label="试运行与事件" name="events" />
      </ElTabs>
      <template v-if="tab === 'rules'">
        <ElAlert
          v-if="legacy.length"
          title="发布R等级前，请迁移以下旧LV引用"
          type="warning"
          :closable="false"
          style="margin-bottom: 16px"
        >
          <p>
            定价策略请在预算中心新建采用R/A等级的版本并下架旧版本；旧分群请建立新分群、切换引用后归档。
          </p>
          <div v-for="item in legacy" :key="`${item.type}:${item.id}`">
            {{ item.type === "pricing" ? "定价策略" : "动态分群" }} · {{ item.name }}
            <ElButton
              v-if="item.type === 'segment'"
              v-hasPerm="['workspace:rule:manage']"
              link
              type="primary"
              :disabled="busy"
              @click="archiveLegacy(item.id)"
              >归档旧分群</ElButton
            >
          </div>
        </ElAlert>
        <FaSearchBar
          v-show="showSearchBar"
          :model-value="query"
          :items="searchItems"
          :span="8"
          class="growth-search-card"
          :is-expand="false"
          :show-expand="false"
          @update:model-value="Object.assign(query, $event)"
          @search="search"
          @reset="reset"
        />
        <ElCard class="fa-table-card growth-table-card" shadow="never">
          <FaTableHeader
            v-model:columns="columnChecks"
            v-model:showSearchBar="showSearchBar"
            :loading="loading"
            @refresh="load"
          >
            <template #left>
              <ElButton
                v-if="!rows.length && !loading && !failed"
                v-hasPerm="['workspace:rule:manage']"
                :loading="busy"
                @click="seed"
                ><FaSvgIcon icon="ri:file-add-line" />载入初始规则</ElButton
              >
              <ElButton
                v-if="kind === 'incentive'"
                v-hasPerm="['workspace:rule:manage']"
                type="primary"
                @click="create"
                ><FaSvgIcon icon="ri:add-line" />新建规则</ElButton
              >
              <ElCheckbox v-model="history" @change="pageNo = 1">显示历史版本</ElCheckbox>
            </template>
          </FaTableHeader>
          <ElAlert v-if="failed" title="规则加载失败，请重试" type="error" :closable="false" />
          <FaTable
            :loading="loading"
            :data="pageRows"
            :columns="columns"
            :pagination="pagination"
            :pagination-options="{ align: 'right' }"
            @pagination:size-change="
              pageSize = $event;
              pageNo = 1;
            "
            @pagination:current-change="pageNo = $event"
          />
        </ElCard>
      </template>
      <ElCard v-else class="fa-table-card growth-table-card" shadow="never">
        <AuditPanel :kind="auditKind" :scope="currentApp.id!" />
      </ElCard>
    </template>
    <ElDrawer
      v-model="editorVisible"
      :title="`${editor?.id ? '编辑' : '新建'}${titles[kind]}`"
      class="growth-editor"
      size="min(900px, 96vw)"
      :close-on-click-modal="false"
      destroy-on-close
    >
      <div v-if="editor" class="growth-editor-content">
        <ElForm label-position="top" class="growth-form-section" :disabled="busy"
          ><ElFormItem label="规则名称"><ElInput v-model="editor.name" maxlength="80" /></ElFormItem
          ><ElFormItem v-if="kind === 'incentive'" label="规则编号（英文，发布后不可变更）"
            ><ElInput
              v-model="editor.key"
              :disabled="Boolean(editor.id)"
              maxlength="64" /></ElFormItem
        ></ElForm>
        <GradeEditor
          v-if="kind === 'usage' || kind === 'promotion'"
          :model-value="editor.config as GradePolicy"
          @update:model-value="editor.config = $event"
        />
        <RightsEditor
          v-else-if="kind === 'rights'"
          :model-value="editor.config as RightsPolicy"
          @update:model-value="editor.config = $event"
        />
        <IncentiveEditor
          v-else
          :model-value="editor.config as IncentivePolicy"
          @update:model-value="editor.config = $event"
        />
      </div>
      <template #footer
        ><ElText v-if="saveProblem" type="warning" class="growth-save-hint">{{
          saveProblem
        }}</ElText
        ><ElButton
          v-if="editor && kind !== 'incentive'"
          :disabled="busy"
          @click="showPresentation(editor, true)"
          ><FaSvgIcon icon="ri:eye-line" />预览效果</ElButton
        ><ElButton :disabled="busy" @click="editorVisible = false">取消</ElButton
        ><ElButton type="primary" :loading="busy" :disabled="!!saveProblem" @click="save"
          >保存并发布</ElButton
        ></template
      >
    </ElDrawer>
    <ElDrawer
      v-model="presentationVisible"
      :title="`${titles[kind]} · 效果预览`"
      size="min(1440px, 96vw)"
      destroy-on-close
      append-to-body
    >
      <PolicyPresentation
        v-if="presentationRule"
        :rule="presentationRule"
        :unsaved="presentationUnsaved"
      />
      <template #footer
        ><ElButton @click="presentationVisible = false">{{
          presentationUnsaved ? "返回编辑" : "关闭预览"
        }}</ElButton
        ><ElButton
          v-if="presentationRule && !presentationUnsaved"
          v-hasPerm="['workspace:rule:manage']"
          type="primary"
          @click="edit(presentationRule)"
          ><FaSvgIcon icon="ri:edit-line" />编辑规则</ElButton
        ></template
      >
    </ElDrawer>
    <ElDrawer v-model="detailVisible" title="规则详情" size="min(1000px, 96vw)" destroy-on-close>
      <RuleDetails v-if="detail" :rule="detail" :budget-usage="detailBudget" />
      <template #footer
        ><ElButton @click="detailVisible = false">关闭</ElButton
        ><ElButton
          v-if="detail"
          v-hasPerm="['workspace:rule:manage']"
          type="primary"
          @click="edit(detail)"
          ><FaSvgIcon icon="ri:edit-line" />编辑规则</ElButton
        ></template
      >
    </ElDrawer>
    <ElDialog
      :model-value="Boolean(publishTarget)"
      title="发布规则"
      width="min(480px, 92vw)"
      @close="publishTarget = null"
    >
      <p>{{ publishTarget?.name }} · V{{ publishTarget?.version }}</p>
      <ElForm label-position="top"
        ><ElFormItem label="生效时间"
          ><ElDatePicker
            v-model="effectiveAt"
            type="datetime"
            value-format="YYYY-MM-DDTHH:mm:ssZ" /></ElFormItem
      ></ElForm>
      <ElText type="info"
        >发布后按本版本执行；修改需保存新版本。等级规则存在旧分群或定价引用时，需先完成迁移。</ElText
      >
      <template #footer
        ><ElButton @click="publishTarget = null">取消</ElButton
        ><ElButton type="primary" :loading="busy" :disabled="!effectiveAt" @click="publish"
          >确认发布</ElButton
        ></template
      >
    </ElDialog>
    <ElDrawer
      class="growth-preview"
      v-model="previewVisible"
      title="等级计算预览"
      size="min(1100px, 96vw)"
    >
      <ElAlert
        title="预览不会修改用户等级。数据不足时不会强制降级。"
        :closable="false"
        type="info"
      />
      <ElTable v-loading="previewLoading" :data="previews"
        ><ElTableColumn type="expand"
          ><template #default="{ row }"
            ><ElDescriptions :column="2" border
              ><ElDescriptionsItem
                v-for="(value, key) in row.metrics"
                :key="key"
                :label="metricName(String(key))"
                >{{ value === null ? "样本不足" : value }}</ElDescriptionsItem
              ><ElDescriptionsItem label="统计窗口">{{ row.window_days }} 天</ElDescriptionsItem
              ><ElDescriptionsItem label="评估时间">{{
                row.evaluated_at
              }}</ElDescriptionsItem></ElDescriptions
            ></template
          ></ElTableColumn
        ><ElTableColumn prop="name" label="用户" /><ElTableColumn label="当前等级"
          ><template #default="{ row }"><RuleTag :value="row.old_grade" /></template></ElTableColumn
        ><ElTableColumn label="评估结果"
          ><template #default="{ row }"><RuleTag :value="row.new_grade" /></template></ElTableColumn
        ><ElTableColumn prop="score" label="综合分" /><ElTableColumn
          prop="reason"
          label="说明"
          min-width="180"
      /></ElTable>
      <ElPagination
        class="growth-pagination"
        v-model:current-page="previewPage"
        :total="previewTotal"
        :page-size="20"
        layout="total, prev, pager, next"
        @current-change="preview()"
      />
    </ElDrawer>
  </main>
</template>
<style scoped lang="scss">
.growth-page :deep(.growth-tag-group) {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.growth-page {
  :deep(.growth-search-card) {
    margin-bottom: 16px;
    flex-shrink: 0;
  }
  .growth-table-card {
    margin-top: 0;
  }
  .growth-table-card > :deep(.el-card__body) {
    padding: 20px;
  }
  .growth-tabs {
    flex-shrink: 0;
    margin-bottom: 12px;
  }
  .growth-tabs :deep(.el-tabs__header) {
    margin-bottom: 0;
  }
  .growth-tabs :deep(.el-tabs__content) {
    display: none;
  }
}
.growth-save-hint {
  display: block;
  margin-bottom: 12px;
  text-align: left;
}
.growth-editor-content {
  padding: 16px;
  border-radius: 10px;
  background: var(--el-fill-color-light);
  :deep(.growth-form-section) {
    padding: 20px;
    border: 1px solid var(--el-border-color-lighter);
    background: var(--el-bg-color);
    border-radius: 10px;
    margin-bottom: 20px;
  }
  :deep(.growth-form-section > header) {
    display: flex;
    align-items: center;
    gap: 10px;
    font-weight: 600;
    margin-bottom: 16px;
  }
  :deep(.el-form-item) {
    margin-bottom: 18px;
  }
}
.growth-pagination {
  justify-content: flex-end;
  margin-top: 20px;
  overflow-x: auto;
}
.growth-editor-content :deep(.growth-form-grid) {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 0 20px;
  margin-top: 16px;
  .el-input-number {
    width: 100%;
  }
}
.growth-editor-content :deep(.growth-condition) {
  display: grid;
  grid-template-columns: minmax(150px, 1.5fr) minmax(100px, 1fr) 150px auto;
  gap: 10px;
  margin-bottom: 12px;
}
.growth-page :deep(.el-pagination) {
  margin-top: 16px;
  justify-content: flex-end;
}
@media (max-width: 640px) {
  .growth-editor-content :deep(.growth-condition) {
    grid-template-columns: 1fr 1fr;
  }
}
</style>
