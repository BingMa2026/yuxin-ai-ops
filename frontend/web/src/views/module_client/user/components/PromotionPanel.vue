<script setup lang="ts">
import { ref, watch } from "vue";
import { ElMessageBox } from "element-plus";
import GrowthAPI, {
  type GrowthProfile,
  type Referral,
  metricLabels,
  type Metric,
} from "@/api/module_growth";
const props = defineProps<{ userId: number }>();
const profile = ref<GrowthProfile>(),
  rows = ref<Referral[]>([]),
  page = ref(1),
  total = ref(0),
  loading = ref(false),
  failed = ref(false),
  busy = ref(false);
const riskNames: Record<string, string> = {
  pending: "待核验",
  passed: "有效",
  rejected: "不计入推广",
};
let generation = 0;
async function load() {
  const sequence = ++generation;
  loading.value = true;
  failed.value = false;
  try {
    const [p, r] = await Promise.all([
      GrowthAPI.profile(props.userId),
      GrowthAPI.referrals(props.userId, page.value),
    ]);
    if (sequence !== generation) return;
    profile.value = p.data.data;
    rows.value = r.data.data.items;
    total.value = r.data.data.total;
  } catch {
    if (sequence === generation) failed.value = true;
  } finally {
    if (sequence === generation) loading.value = false;
  }
}
async function review(row: Referral, approved: boolean) {
  const input = await ElMessageBox.prompt(`填写“${row.name}”邀请关系的核验依据`, "推广合规核验", {
    inputValidator: (v) => Boolean(v?.trim().length >= 2) || "至少填写2个字符",
  }).catch(() => null);
  if (!input) return;
  busy.value = true;
  try {
    await GrowthAPI.review("referrals", row.id, approved, input.value);
    await load();
  } finally {
    busy.value = false;
  }
}
watch(
  () => props.userId,
  () => {
    page.value = 1;
    profile.value = undefined;
    rows.value = [];
    void load();
  },
  { immediate: true }
);
</script>
<template>
  <div v-loading="loading">
    <ElAlert v-if="failed" title="推广数据加载失败" type="error" :closable="false"
      ><ElButton text @click="load">重试</ElButton></ElAlert
    >
    <template v-if="profile">
      <ElDescriptions :column="2" border>
        <ElDescriptionsItem label="用户等级"
          ><ElTag>{{ profile.usage_grade }}</ElTag></ElDescriptionsItem
        >
        <ElDescriptionsItem label="推广等级"
          ><ElTag type="success">{{
            profile.promotion_grade === "ungraded" ? "未定级" : profile.promotion_grade
          }}</ElTag></ElDescriptionsItem
        >
        <ElDescriptionsItem label="专属邀请码">{{ profile.invite_code }}</ElDescriptionsItem
        ><ElDescriptionsItem label="累计邀请">{{ profile.invited_count }} 人</ElDescriptionsItem>
        <ElDescriptionsItem label="邀请所得积分">{{
          profile.reward_totals.credits || 0
        }}</ElDescriptionsItem
        ><ElDescriptionsItem label="邀请所得现金"
          >¥{{ ((profile.reward_totals.cash || 0) / 100).toFixed(2) }}</ElDescriptionsItem
        >
      </ElDescriptions>
      <ElDivider content-position="left">定级依据</ElDivider>
      <ElEmpty
        v-if="!profile.evaluations.promotion"
        description="尚未完成推广等级评估，发布规则后按周期计算"
        :image-size="64"
      />
      <template v-else>
        <p>
          {{ profile.evaluations.promotion.window_days }}天统计窗口 ·
          {{ new Date(profile.evaluations.promotion.evaluated_at).toLocaleString() }}
        </p>
        <ElDescriptions :column="2" border
          ><ElDescriptionsItem
            v-for="(value, key) in profile.evaluations.promotion.metrics"
            :key="key"
            :label="metricLabels[key as Metric] || key"
            >{{ value ?? "样本不足" }}</ElDescriptionsItem
          ></ElDescriptions
        >
      </template>
      <ElDivider content-position="left">邀请明细</ElDivider>
      <ElTable :data="rows" empty-text="暂无邀请记录">
        <ElTableColumn prop="name" label="受邀用户" min-width="120" />
        <ElTableColumn label="绑定时间" min-width="170"
          ><template #default="{ row }">{{
            new Date(row.bound_at).toLocaleString()
          }}</template></ElTableColumn
        >
        <ElTableColumn label="转化进度" min-width="120"
          ><template #default="{ row }">{{
            row.first_paid_at ? "已付费" : row.first_task_at ? "已首次使用" : "已注册"
          }}</template></ElTableColumn
        >
        <ElTableColumn label="合规状态" width="125"
          ><template #default="{ row }">{{
            riskNames[row.risk_status] || row.risk_status
          }}</template></ElTableColumn
        >
        <ElTableColumn label="核验" width="130"
          ><template #default="{ row }"
            ><template v-if="row.risk_status === 'pending'"
              ><ElButton
                v-hasPerm="['workspace:rule:manage']"
                link
                type="primary"
                :disabled="busy"
                @click="review(row as Referral, true)"
                >有效</ElButton
              ><ElButton
                v-hasPerm="['workspace:rule:manage']"
                link
                type="danger"
                :disabled="busy"
                @click="review(row as Referral, false)"
                >无效</ElButton
              ></template
            ></template
          ></ElTableColumn
        >
      </ElTable>
      <ElPagination
        v-model:current-page="page"
        :total="total"
        :page-size="20"
        layout="total, prev, pager, next"
        @current-change="load"
      />
    </template>
  </div>
</template>
