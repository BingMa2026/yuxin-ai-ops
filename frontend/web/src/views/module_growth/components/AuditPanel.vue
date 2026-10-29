<script setup lang="ts">
import { ref, watch } from "vue";
import { ElMessageBox } from "element-plus";
import GrowthAPI, { type AuditRow } from "@/api/module_growth";
import RuleTag from "./RuleTag.vue";
const taskNames: Record<string, string> = {
  tender_analysis: "招标解析",
  full_review: "完整审查",
  cocreate: "共创",
  first_task: "首次有效任务",
  first_subscription: "首次订阅付费",
  first_traffic: "首次流量包付费",
  daily_login: "每日登录",
  artifact: "有效成果",
  feedback: "反馈采纳",
};
const props = defineProps<{ kind: "rewards" | "tasks" | "events"; scope: number }>();
const rows = ref<AuditRow[]>([]),
  loading = ref(false),
  failed = ref(false),
  page = ref(1),
  total = ref(0),
  busy = ref(false);
const labels: Record<string, string> = {
  simulated: "试运行",
  matched: "已匹配",
  skipped: "未匹配",
  review: "待审核",
  pending: "待到账",
  posted: "已到账",
  rejected: "已拒绝",
  reversed: "已冲正",
  started: "进行中",
  verified: "已核验",
  failed: "失败",
  cancelled: "已取消",
};
let loadGeneration = 0;
async function load() {
  const generation = ++loadGeneration;
  loading.value = true;
  failed.value = false;
  try {
    const result = (await GrowthAPI.auditRows(props.kind, page.value)).data.data;
    if (generation === loadGeneration) {
      rows.value = result.items;
      total.value = result.total;
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
async function review(row: AuditRow, approved: boolean) {
  if (props.kind === "events") return;
  const input = await ElMessageBox.prompt(
    `请填写${approved ? "通过" : "拒绝"} #${row.id} 的审核依据`,
    "审核",
    { inputValidator: (v) => Boolean(v?.trim().length >= 2) || "请填写至少2个字符" }
  ).catch(() => null);
  if (!input) return;
  busy.value = true;
  try {
    await GrowthAPI.review(props.kind, row.id, approved, input.value);
    await load();
  } finally {
    busy.value = false;
  }
}
watch(
  () => [props.kind, props.scope],
  () => {
    page.value = 1;
    rows.value = [];
    void load();
  },
  { immediate: true }
);
</script>
<template>
  <div class="growth-audit">
    <ElAlert v-if="failed" title="记录加载失败" type="error" :closable="false"
      ><ElButton text @click="load">重试</ElButton></ElAlert
    >
    <ElTable height="100%" v-loading="loading" :data="rows" empty-text="暂无记录">
      <ElTableColumn v-if="kind === 'events'" type="expand"
        ><template #default="{ row }"
          ><div
            v-for="simulation in row.facts?.simulation_results || []"
            :key="simulation.policy_id"
            style="padding: 12px 20px"
          >
            <strong>{{ simulation.name }} · V{{ simulation.version }}</strong>
            <p v-for="award in simulation.rewards" :key="`${award.user_id}:${award.asset}`">
              用户 {{ award.user_id }} · 预计
              {{
                award.asset === "cash"
                  ? `¥${(award.amount / 100).toFixed(2)}`
                  : `${award.amount} 积分`
              }}（未入账）
            </p>
          </div></template
        ></ElTableColumn
      ><ElTableColumn prop="id" label="编号" width="90" /><ElTableColumn
        prop="user_id"
        label="用户ID"
        width="100"
      />
      <ElTableColumn
        :label="kind === 'rewards' ? '奖励' : kind === 'events' ? '事件' : '任务'"
        min-width="170"
        ><template #default="{ row }"
          >{{ row.snapshot?.name || taskNames[String(row.kind)] || row.kind }}
          <div v-if="row.project_ref">
            <ElText size="small" type="info">{{ row.project_ref }}</ElText>
          </div></template
        ></ElTableColumn
      >
      <ElTableColumn
        v-if="kind === 'tasks'"
        prop="verified_model_calls"
        label="已核验模型调用"
        width="140"
      /><ElTableColumn v-if="kind === 'rewards'" label="金额 / 积分" width="130"
        ><template #default="{ row }">{{
          row.asset === "cash" ? `¥${(row.amount / 100).toFixed(2)}` : `${row.amount} 积分`
        }}</template></ElTableColumn
      >
      <ElTableColumn label="状态" width="120"
        ><template #default="{ row }"
          ><RuleTag :value="row.status" :label="labels[row.status]" /></template
      ></ElTableColumn>
      <ElTableColumn label="处理说明" min-width="160"
        ><template #default="{ row }">{{
          row.reason || row.review_reason || "—"
        }}</template></ElTableColumn
      >
      <ElTableColumn label="操作" width="150" fixed="right"
        ><template #default="{ row }"
          ><template v-if="kind !== 'events' && row.status === 'review'"
            ><ElButton
              v-hasPerm="['workspace:rule:manage']"
              link
              type="primary"
              :disabled="busy"
              @click="review(row as AuditRow, true)"
              >通过</ElButton
            ><ElButton
              v-hasPerm="['workspace:rule:manage']"
              link
              type="danger"
              :disabled="busy"
              @click="review(row as AuditRow, false)"
              >拒绝</ElButton
            ></template
          ></template
        ></ElTableColumn
      >
    </ElTable>
    <ElPagination
      class="audit-pagination"
      v-model:current-page="page"
      :page-size="20"
      :total="total"
      layout="total, prev, pager, next"
      @current-change="load"
    />
  </div>
</template>

<style scoped>
.growth-audit {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
}
.growth-audit > .el-table {
  flex: 1;
}
.audit-pagination {
  flex-shrink: 0;
  display: flex;
  justify-content: flex-end;
  padding-top: 20px;
  overflow-x: auto;
}
</style>
