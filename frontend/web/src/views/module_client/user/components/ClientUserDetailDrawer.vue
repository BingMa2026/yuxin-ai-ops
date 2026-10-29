<template>
  <ElDrawer v-model="visible" class="user-detail-drawer" size="min(1160px, 96vw)" destroy-on-close>
    <template #header>
      <div class="drawer-heading">
        <strong>用户档案</strong><small>用户价值、产品活跃与服务记录</small>
      </div>
    </template>
    <div v-if="user" class="detail-body">
      <section class="profile-hero">
        <div class="profile-identity">
          <ElAvatar :size="52" :src="user.avatar" :style="{ background: avatarColor }">{{
            avatarText
          }}</ElAvatar>
          <div>
            <div class="profile-name">
              <h2>{{ user.display_name || user.username }}</h2>
              <ElTag :type="user.status === 'active' ? 'success' : 'danger'" effect="plain" round>{{
                user.status === "active" ? "正常" : "已停用"
              }}</ElTag>
            </div>
            <p>{{ user.company_name || "未填写企业" }}</p>
            <small>账号 {{ user.username }} · 用户 ID {{ user.id }}</small>
          </div>
        </div>
        <div class="profile-value">
          <span>当前用户等级</span>
          <ElTag class="profile-level-tag" :type="levelInfo.type" effect="dark" round>{{
            user.usage_grade || "R1"
          }}</ElTag>
          <small
            >推广等级
            {{
              user.promotion_grade === "ungraded" ? "未定级" : user.promotion_grade || "未定级"
            }}</small
          >
        </div>
      </section>

      <section class="headline-metrics" aria-label="用户关键指标">
        <div>
          <span>近 30 日活跃</span><strong>{{ activeDays }}<small> 天</small></strong>
          <p>{{ recentActivityCount.toLocaleString() }} 次产品行为</p>
        </div>
        <div>
          <span>近 30 日模型调用</span
          ><strong>{{ calls30d.toLocaleString() }}<small> 次</small></strong>
          <p>{{ compact(tokens30d) }} Token</p>
        </div>
        <div>
          <span>累计支付</span><strong>¥{{ (user.total_paid_fen / 100).toFixed(2) }}</strong>
          <p>{{ user.current_subscription || "暂未订阅" }}</p>
        </div>
        <div>
          <template v-if="localMode"
            ><span>订阅到期时间</span
            ><strong>{{ user.subscription_expires_at || "未开通" }}</strong>
            <p>自配模型 · 按订阅时间使用</p></template
          >
          <template v-else
            ><span>可用积分</span><strong>{{ user.available_credits.toLocaleString() }}</strong>
            <p>{{ user.pending_credits.toLocaleString() }} 待释放</p></template
          >
        </div>
      </section>

      <p class="mb-4">
        当前使用模式：{{ activity ? billingModeLabel(activity.active_billing_mode) : "待同步" }}
      </p>
      <div v-if="activity?.risk_flags.length" class="risk-row">
        <ElAlert
          v-for="item in activity.risk_flags"
          :key="item.code"
          :title="item.label"
          :type="item.level === 'high' ? 'error' : 'warning'"
          :closable="false"
          show-icon
        />
      </div>

      <ElTabs v-model="tab" class="detail-tabs">
        <ElTabPane label="推广与定级" name="promotion" lazy
          ><PromotionPanel v-if="tab === 'promotion'" :user-id="user.id!"
        /></ElTabPane>
        <ElTabPane label="基本档案" name="profile">
          <div class="profile-layout">
            <section class="content-card profile-fields">
              <header class="section-heading">
                <div>
                  <h3>基本资料</h3>
                  <p>账号身份与可联系信息</p>
                </div>
              </header>
              <dl>
                <div>
                  <dt>注册来源</dt>
                  <dd>{{ registrationSourceName(user.registration_source) }}</dd>
                </div>
                <div>
                  <dt>手机号码</dt>
                  <dd>{{ user.mobile || "—" }}</dd>
                </div>
                <div>
                  <dt>电子邮箱</dt>
                  <dd>{{ user.email || "—" }}</dd>
                </div>
                <div>
                  <dt>注册时间</dt>
                  <dd>{{ formatTime(user.registered_at) }}</dd>
                </div>
                <div>
                  <dt>最后登录</dt>
                  <dd>{{ formatTime(user.last_login_at) }}</dd>
                </div>
                <div>
                  <dt>最后活跃</dt>
                  <dd>{{ formatTime(user.last_active_at) }}</dd>
                </div>
                <div class="field-wide">
                  <dt>运营备注</dt>
                  <dd>{{ user.description || "暂无运营备注" }}</dd>
                </div>
              </dl>
            </section>

            <section class="content-card score-card">
              <header class="section-heading">
                <div>
                  <h3>旧版 LV 评分（历史兼容）</h3>
                  <p>最近评估 {{ formatTime(user.level_evaluated_at) }}</p>
                </div>
                <strong>{{ user.level_score.toFixed(1) }}</strong>
              </header>
              <div class="score-list">
                <div v-for="item in scoreMetrics" :key="item.key">
                  <div>
                    <span>{{ item.label }}</span
                    ><strong>{{ item.display }}</strong>
                  </div>
                  <ElProgress :percentage="item.percentage" :show-text="false" :stroke-width="6" />
                </div>
              </div>
            </section>

            <section class="content-card activity-panel">
              <header class="section-heading activity-heading">
                <div>
                  <h3>近 30 日活跃趋势</h3>
                  <p>综合客户端核心事件、登录与模型调用，不采集业务正文</p>
                </div>
                <div class="activity-summary">
                  <span><i class="dot dot--blue" />{{ activeDays }} 个活跃日</span
                  ><span><i class="dot dot--violet" />{{ calls30d }} 次模型调用</span>
                </div>
              </header>
              <FaECharts v-if="hasActivity" :options="activityOptions" height="220px" />
              <ElEmpty v-else :image-size="64" description="近 30 日暂无活跃记录" />
            </section>

            <section class="content-card tag-card">
              <header class="section-heading">
                <div>
                  <h3>人工标签</h3>
                  <p>用于筛选、分群和精细化运营</p>
                </div>
              </header>
              <div class="tag-row">
                <ElTag
                  v-for="tag in user.tags"
                  :key="tag.id"
                  closable
                  effect="plain"
                  @close="$emit('remove-tag', tag.id!)"
                  >{{ tag.name }}</ElTag
                >
                <span v-if="!user.tags.length" class="empty-text">尚未添加标签</span>
                <ElButton
                  v-hasPerm="['workspace:user:management:update']"
                  link
                  type="primary"
                  @click="$emit('add-tag')"
                  >+ 添加标签</ElButton
                >
              </div>
            </section>
          </div>
        </ElTabPane>

        <ElTabPane label="订阅与订单" name="subscription">
          <div v-if="activity?.subscription" class="subscription-card">
            <div>
              <span>当前订阅</span
              ><strong>{{ activity.subscription.plan_name || "当前订阅" }}</strong>
            </div>
            <ElTag type="success" effect="plain">{{
              subscriptionStatus(activity.subscription.status)
            }}</ElTag>
            <p>
              {{ formatTime(activity.subscription.current_period_start) }} —
              {{ formatTime(activity.subscription.current_period_end) }}
            </p>
            <small>{{ activity.subscription.auto_renew ? "自动续费" : "手动续费" }}</small>
          </div>
          <ElTable v-if="activity?.orders.length" :data="activity.orders" size="small">
            <ElTableColumn prop="order_no" label="订单号" min-width="190" /><ElTableColumn
              prop="plan_name"
              label="套餐"
            />
            <ElTableColumn label="金额"
              ><template #default="{ row }"
                >¥{{ (row.amount_fen / 100).toFixed(2) }}</template
              ></ElTableColumn
            >
            <ElTableColumn label="状态"
              ><template #default="{ row }"
                ><ElTag size="small" effect="plain">{{ orderStatus(row.status) }}</ElTag></template
              ></ElTableColumn
            >
          </ElTable>
          <EmptyPanel
            v-else
            icon="ri:calendar-check-line"
            title="暂无订阅和订单"
            description="客户端完成支付后，这里会展示订单快照与当前订阅周期。"
          />
          <div v-if="activity?.subscription_cycles.length" class="section-block">
            <h3>订阅周期</h3>
            <ElTable :data="activity.subscription_cycles" size="small">
              <ElTableColumn prop="cycle_no" label="周期" width="70" /><ElTableColumn
                prop="plan_name"
                label="套餐"
              />
              <ElTableColumn prop="starts_at" label="开始时间" min-width="150" /><ElTableColumn
                prop="ends_at"
                label="结束时间"
                min-width="150"
              />
              <ElTableColumn label="状态" width="90"
                ><template #default="{ row }">{{
                  subscriptionStatus(row.status)
                }}</template></ElTableColumn
              >
            </ElTable>
          </div>
        </ElTabPane>

        <ElTabPane v-if="!localMode" label="积分账户" name="credits">
          <div class="metric-grid">
            <MetricCard label="可用积分" :value="user.available_credits" /><MetricCard
              label="待释放积分"
              :value="user.pending_credits"
            /><MetricCard label="30天内到期" :value="activity?.expiring_credits || 0" /><MetricCard
              label="累计消耗"
              :value="user.credit_usage"
            />
          </div>
          <ElTable
            v-if="activity?.credit_ledger.length"
            :data="activity.credit_ledger"
            size="small"
          >
            <ElTableColumn prop="entry_type" label="类型" /><ElTableColumn label="变动"
              ><template #default="{ row }"
                ><span :class="row.amount >= 0 ? 'positive' : 'negative'"
                  >{{ row.amount >= 0 ? "+" : "" }}{{ row.amount }}</span
                ></template
              ></ElTableColumn
            >
            <ElTableColumn prop="balance_after" label="变动后余额" /><ElTableColumn
              prop="reason"
              label="原因"
              show-overflow-tooltip
            />
          </ElTable>
          <EmptyPanel
            v-else
            icon="ri:exchange-funds-line"
            title="暂无积分流水"
            description="积分流水不可修改；人工调整会记录原因和操作人。"
          />
        </ElTabPane>

        <ElTabPane label="模型用量" name="usage">
          <div class="metric-grid">
            <MetricCard label="项目数量" :value="activity?.project_count || 0" /><MetricCard
              label="模型调用"
              :value="user.model_calls"
            /><MetricCard label="Token 用量" :value="user.token_usage" /><MetricCard
              label="失败次数"
              :value="user.failed_calls"
            />
          </div>
          <ElTable v-if="activity?.model_usage.length" :data="activity.model_usage" size="small">
            <ElTableColumn prop="business_code" label="业务" /><ElTableColumn
              prop="provider_model_id"
              label="模型"
            />
            <ElTableColumn label="Token"
              ><template #default="{ row }">{{
                row.input_tokens + row.output_tokens
              }}</template></ElTableColumn
            ><ElTableColumn prop="charged_credits" label="积分" />
            <ElTableColumn label="模型成本"
              ><template #default="{ row }"
                ><span class="cost-cell"
                  >¥{{ Number(row.provider_cost_yuan || 0).toFixed(4) }}
                  <ElTag
                    size="small"
                    effect="plain"
                    :type="row.cost_precision === 'actual_usage' ? 'success' : 'warning'"
                    >{{
                      row.reconciliation_status === "reconciled"
                        ? "已核对"
                        : row.cost_precision === "actual_usage"
                          ? "实算"
                          : "估算"
                    }}</ElTag
                  >
                </span></template
              ></ElTableColumn
            >
            <ElTableColumn label="状态"
              ><template #default="{ row }"
                ><ElTag
                  :type="row.status === 'succeeded' ? 'success' : 'danger'"
                  effect="plain"
                  size="small"
                  >{{ row.status === "succeeded" ? "成功" : "失败" }}</ElTag
                ></template
              ></ElTableColumn
            >
          </ElTable>
          <EmptyPanel
            v-else
            icon="ri:line-chart-line"
            title="暂无用量记录"
            description="模型网关启用后按当前客户端持续汇总，不采集聊天正文。"
          />
        </ElTabPane>

        <ElTabPane label="工单与反馈" name="support">
          <ElTable
            v-if="activity?.support_tickets.length"
            :data="activity.support_tickets"
            size="small"
          >
            <ElTableColumn prop="ticket_no" label="工单号" min-width="170" /><ElTableColumn
              prop="subject"
              label="标题"
              min-width="200"
              show-overflow-tooltip
            />
            <ElTableColumn label="性质" width="80"
              ><template #default="{ row }">{{
                row.kind === "complaint" ? "客诉" : "反馈"
              }}</template></ElTableColumn
            >
            <ElTableColumn label="优先级" width="90"
              ><template #default="{ row }"
                ><ElTag :type="priorityType(row.priority)" effect="plain" size="small">{{
                  priorityName(row.priority)
                }}</ElTag></template
              ></ElTableColumn
            >
            <ElTableColumn label="状态" width="100"
              ><template #default="{ row }">{{ ticketStatus(row.status) }}</template></ElTableColumn
            ><ElTableColumn prop="created_time" label="提交时间" min-width="160" />
          </ElTable>
          <EmptyPanel
            v-else
            icon="ri:customer-service-2-line"
            title="暂无工单与反馈"
            description="客户端提交问题后会显示在这里。"
          />
        </ElTabPane>

        <ElTabPane label="登录安全" name="security">
          <ElTable
            v-if="activity?.security_events.length"
            :data="activity.security_events"
            size="small"
          >
            <ElTableColumn label="结果" width="80"
              ><template #default="{ row }"
                ><ElTag :type="row.success ? 'success' : 'danger'" size="small">{{
                  row.success ? "成功" : "失败"
                }}</ElTag></template
              ></ElTableColumn
            >
            <ElTableColumn label="动作" width="90"
              ><template #default="{ row }">{{
                row.action === "login" ? "登录" : row.action === "register" ? "注册" : row.action
              }}</template></ElTableColumn
            >
            <ElTableColumn prop="request_ip" label="IP" min-width="120" /><ElTableColumn
              prop="failure_reason"
              label="失败原因"
              min-width="150"
              show-overflow-tooltip
            /><ElTableColumn prop="created_time" label="时间" min-width="160" />
          </ElTable>
          <EmptyPanel
            v-else
            icon="ri:shield-user-line"
            title="暂无登录事件"
            description="客户端登录和注册成功、失败及限流事件会保留在这里。"
          />
        </ElTabPane>
      </ElTabs>
    </div>
  </ElDrawer>
</template>

<script setup lang="ts">
import { billingModeLabel } from "@/api/module_client/app";
const localMode = computed(() => props.activity?.active_billing_mode === "duration");
import PromotionPanel from "./PromotionPanel.vue";
import dayjs from "dayjs";
import type { EChartsOption } from "@/plugins/echarts";
import type { ClientUserActivity, ClientUserInfo } from "@/api/module_client/user";
import FaECharts from "@/components/charts/fa-echarts/index.vue";
import { useSettingsStore } from "@stores";
import EmptyPanel from "./EmptyPanel.vue";
import MetricCard from "./MetricCard.vue";

const props = defineProps<{
  modelValue: boolean;
  user?: ClientUserInfo;
  activity?: ClientUserActivity;
}>();
const emit = defineEmits<{
  "update:modelValue": [boolean];
  "add-tag": [];
  "remove-tag": [number];
}>();
const { isDark } = storeToRefs(useSettingsStore());
const visible = computed({
  get: () => props.modelValue,
  set: (value) => emit("update:modelValue", value),
});
const tab = ref("profile");
watch(localMode, (local) => {
  if (local && tab.value === "credits") tab.value = "profile";
});
const palette = ["#4f7ff7", "#18a879", "#d89b22", "#d96c4e", "#7c69d5", "#2498b8"];
const avatarColor = computed(() => {
  const key = props.user?.username || "用户";
  return palette[[...key].reduce((sum, char) => sum + char.charCodeAt(0), 0) % palette.length];
});
const avatarText = computed(() =>
  (props.user?.display_name || props.user?.username || "用").slice(0, 1).toUpperCase()
);
const levelInfo = computed(
  () =>
    ({
      R1: { type: "info" as const },
      R2: { type: "success" as const },
      R3: { type: "primary" as const },
    })[props.user?.usage_grade || "R1"]
);
const trend = computed(() => props.activity?.activity_trend || []);
const activeDays = computed(
  () =>
    trend.value.filter((item) => item.calls + (item.events || 0) + (item.logins || 0) > 0).length
);
const calls30d = computed(() => trend.value.reduce((sum, item) => sum + item.calls, 0));
const tokens30d = computed(() => trend.value.reduce((sum, item) => sum + item.tokens, 0));
const recentActivityCount = computed(() =>
  trend.value.reduce((sum, item) => sum + (item.events || 0) + (item.logins || 0), 0)
);
const hasActivity = computed(() => activeDays.value > 0);
const compact = (value: number) =>
  new Intl.NumberFormat("zh-CN", { notation: "compact", maximumFractionDigits: 1 }).format(
    value || 0
  );
const formatTime = (value?: string | null) =>
  value ? dayjs(value).format("YYYY-MM-DD HH:mm") : "—";
const scoreMetrics = computed(() => {
  const metrics = props.user?.level_metrics || {};
  const definitions = [
    {
      key: "total_paid_fen",
      label: "累计支付",
      cap: 500000,
      format: (value: number) => `¥${(value / 100).toLocaleString()}`,
    },
    {
      key: "active_days_30d",
      label: "近30日活跃",
      cap: 20,
      format: (value: number) => `${value} 天`,
    },
    {
      key: "model_calls_30d",
      label: "近30日模型调用",
      cap: 200,
      format: (value: number) => `${value} 次`,
    },
    {
      key: "credits_used_30d",
      label: "近30日积分消耗",
      cap: 100000,
      format: (value: number) => compact(value),
    },
    {
      key: "feedback_contribution",
      label: "有效反馈",
      cap: 5,
      format: (value: number) => `${value} 条`,
    },
  ];
  return definitions.map((item) => {
    const value = Number(metrics[item.key] || 0);
    return {
      ...item,
      display: item.format(value),
      percentage: Math.min(100, Math.round((value / item.cap) * 100)),
    };
  });
});
const activityOptions = computed<EChartsOption>(() => {
  const textColor = isDark.value ? "#aeb6c2" : "#667085";
  const gridColor = isDark.value ? "#303744" : "#edf0f4";
  const tooltipBg = isDark.value ? "#1b2028" : "#ffffff";
  return {
    color: ["#4f7ff7", "#7c69d5", "#18a879"],
    tooltip: {
      trigger: "axis",
      backgroundColor: tooltipBg,
      borderColor: gridColor,
      formatter: (params: any) => {
        const entries = Array.isArray(params) ? params : [params];
        const index = Number(entries[0]?.dataIndex || 0);
        const point = trend.value[index];
        if (!point) return "";
        return [
          `<b>${dayjs(point.date).format("YYYY-MM-DD")}</b>`,
          `客户端事件：${point.events || 0}`,
          `登录：${point.logins || 0}`,
          `模型调用：${point.calls || 0}`,
          `Token：${Number(point.tokens || 0).toLocaleString("zh-CN")}`,
          `模型成本（含语音）：${point.unknown_cost_calls ? "≥" : ""}¥${Number(point.provider_cost_yuan || 0).toFixed(4)}${point.unknown_cost_calls ? `，${point.unknown_cost_calls} 次待确认` : ""}`,
        ].join("<br/>");
      },
    },
    legend: {
      right: 0,
      top: 0,
      itemWidth: 12,
      itemHeight: 8,
      textStyle: { color: textColor, fontSize: 11 },
    },
    grid: { left: 18, right: 18, top: 42, bottom: 18, containLabel: true },
    xAxis: {
      type: "category",
      boundaryGap: false,
      data: trend.value.map((item) => dayjs(item.date).format("MM/DD")),
      axisLine: { lineStyle: { color: gridColor } },
      axisTick: { show: false },
      axisLabel: { color: textColor, fontSize: 10, interval: 4 },
    },
    yAxis: {
      type: "value",
      minInterval: 1,
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: textColor, fontSize: 10 },
      splitLine: { lineStyle: { color: gridColor } },
    },
    series: [
      {
        name: "客户端事件",
        type: "line",
        smooth: true,
        symbol: "none",
        lineStyle: { width: 2 },
        areaStyle: { opacity: 0.09 },
        data: trend.value.map((item) => item.events || 0),
      },
      {
        name: "模型调用",
        type: "line",
        smooth: true,
        symbol: "none",
        lineStyle: { width: 2 },
        areaStyle: { opacity: 0.06 },
        data: trend.value.map((item) => item.calls),
      },
      {
        name: "登录",
        type: "line",
        smooth: true,
        symbol: "none",
        lineStyle: { width: 1.5, type: "dashed" },
        data: trend.value.map((item) => item.logins || 0),
      },
    ],
  };
});
const registrationSourceName = (source: string) =>
  ({ self: "自主注册", admin: "运营创建", import: "批量导入", invitation: "邀请注册" })[source] ||
  source;
const subscriptionStatus = (status: string) =>
  ({ active: "订阅中", expired: "已到期", canceled: "已取消" })[status] || status;
const orderStatus = (status: string) =>
  ({ pending: "待支付", paid: "已支付", closed: "已关闭", refunded: "已退款" })[status] || status;
const ticketStatus = (status: string) =>
  ({
    pending: "待受理",
    processing: "处理中",
    waiting_user: "待用户补充",
    resolved: "已解决",
    closed: "已关闭",
  })[status] || status;
const priorityName = (priority: string) =>
  ({ urgent: "紧急", high: "高", normal: "普通", low: "低" })[priority] || priority;
const priorityType = (priority: string) =>
  priority === "urgent"
    ? ("danger" as const)
    : priority === "high"
      ? ("warning" as const)
      : priority === "low"
        ? ("info" as const)
        : ("primary" as const);
</script>

<style scoped>
.detail-body {
  padding: 0 4px 24px;
}

.drawer-heading {
  display: grid;
  gap: 3px;
}

.drawer-heading strong {
  font-size: 16px;
  color: var(--el-text-color-primary);
}

.drawer-heading small {
  font-size: 11px;
  font-weight: 400;
  color: var(--el-text-color-secondary);
}

.profile-hero,
.content-card,
.headline-metrics {
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 14px;
}

.profile-hero {
  display: flex;
  gap: 24px;
  align-items: center;
  justify-content: space-between;
  padding: 14px 18px;
  margin-bottom: 10px;
  background: var(--el-bg-color);
}

.profile-identity {
  display: flex;
  gap: 14px;
  align-items: center;
  min-width: 0;
}

.profile-identity > div {
  min-width: 0;
}

.profile-name {
  display: flex;
  gap: 9px;
  align-items: center;
}

.profile-name h2,
.section-heading h3 {
  margin: 0;
  color: var(--el-text-color-primary);
}

.profile-name h2 {
  overflow: hidden;
  text-overflow: ellipsis;
  font-size: 19px;
  white-space: nowrap;
}

.profile-identity p,
.profile-identity small,
.section-heading p,
.headline-metrics p {
  margin: 3px 0 0;
  font-size: 11px;
  color: var(--el-text-color-secondary);
}

.profile-value {
  display: grid;
  grid-template-columns: auto auto;
  gap: 5px 12px;
  align-items: center;
  min-width: 220px;
  padding-left: 20px;
  border-left: 1px solid var(--el-border-color-lighter);
}

.profile-value > span {
  font-size: 11px;
  color: var(--el-text-color-secondary);
}

.profile-value :deep(.profile-level-tag),
.profile-value :deep(.profile-level-tag .el-tag__content) {
  color: #fff !important;
}

.profile-value > strong {
  grid-column: 1 / -1;
  font-size: 22px;
  color: var(--el-text-color-primary);
}

.profile-value > strong small {
  font-size: 11px;
  font-weight: 400;
  color: var(--el-text-color-secondary);
}

.headline-metrics {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  margin-bottom: 10px;
  overflow: hidden;
}

.headline-metrics > div {
  display: grid;
  gap: 5px;
  padding: 12px 16px;
  border-right: 1px solid var(--el-border-color-lighter);
}

.headline-metrics > div:last-child {
  border-right: 0;
}

.headline-metrics span {
  font-size: 11px;
  color: var(--el-text-color-secondary);
}

.headline-metrics strong {
  font-size: 21px;
  color: var(--el-text-color-primary);
  letter-spacing: -0.02em;
}

.headline-metrics strong small {
  font-size: 11px;
  font-weight: 400;
  color: var(--el-text-color-secondary);
}

.risk-row {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  margin-bottom: 10px;
}

.detail-tabs {
  margin-top: 2px;
}

.profile-layout {
  display: grid;
  grid-template-columns: minmax(0, 1.55fr) minmax(300px, 0.75fr);
  gap: 12px;
}

.content-card {
  min-width: 0;
  padding: 17px 18px;
}

.section-heading {
  display: flex;
  gap: 16px;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 15px;
}

.section-heading h3 {
  font-size: 14px;
}

.section-heading > strong {
  font-size: 24px;
  color: var(--el-color-primary);
}

.profile-fields dl {
  display: grid;
  grid-template-columns: 1fr 1fr;
  margin: 0;
}

.profile-fields dl > div {
  display: grid;
  grid-template-columns: 94px minmax(0, 1fr);
  gap: 10px;
  padding: 11px 0;
  border-bottom: 1px solid var(--el-border-color-lighter);
}

.profile-fields dl > div:nth-last-child(2) {
  border-bottom: 0;
}

.profile-fields .field-wide {
  grid-column: 1 / -1;
  border-top: 1px solid var(--el-border-color-lighter);
  border-bottom: 0;
}

.profile-fields dt {
  font-size: 11px;
  color: var(--el-text-color-secondary);
}

.profile-fields dd {
  min-width: 0;
  margin: 0;
  font-size: 12px;
  color: var(--el-text-color-primary);
  overflow-wrap: anywhere;
}

.score-list {
  display: grid;
  gap: 14px;
}

.score-list > div > div {
  display: flex;
  justify-content: space-between;
  margin-bottom: 6px;
}

.score-list span {
  font-size: 11px;
  color: var(--el-text-color-secondary);
}

.score-list strong {
  font-size: 11px;
  color: var(--el-text-color-primary);
}

.activity-panel,
.tag-card {
  grid-column: 1 / -1;
}

.activity-panel {
  order: -1;
  padding-bottom: 8px;
}

.activity-heading {
  align-items: center;
  margin-bottom: 4px;
}

.activity-summary {
  display: flex;
  gap: 15px;
  font-size: 11px;
  color: var(--el-text-color-secondary);
}

.activity-summary span {
  display: flex;
  gap: 6px;
  align-items: center;
}

.dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
}

.dot--blue {
  background: #4f7ff7;
}

.dot--violet {
  background: #7c69d5;
}

.tag-card {
  padding-block: 14px;
}

.tag-card .section-heading {
  margin-bottom: 10px;
}

.tag-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}

.empty-text {
  font-size: 12px;
  color: var(--el-text-color-placeholder);
}

.cost-cell {
  display: inline-flex;
  gap: 6px;
  align-items: center;
}

.metric-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 14px;
}

.subscription-card {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 7px 14px;
  padding: 16px 18px;
  margin-bottom: 12px;
  background: var(--el-fill-color-lighter);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 12px;
}

.subscription-card > div {
  display: grid;
  gap: 3px;
}

.subscription-card span,
.subscription-card p,
.subscription-card small {
  font-size: 11px;
  color: var(--el-text-color-secondary);
}

.subscription-card p {
  grid-column: 1 / -1;
  margin: 0;
}

.positive {
  color: var(--el-color-success);
}

.negative {
  color: var(--el-color-danger);
}

.section-block {
  margin-top: 18px;
}

.section-block h3 {
  margin: 0 0 9px;
  font-size: 13px;
  color: var(--el-text-color-primary);
}
@media (width <= 760px) {
  .profile-hero {
    align-items: flex-start;
  }

  .profile-value {
    min-width: 0;
  }

  .headline-metrics,
  .metric-grid {
    grid-template-columns: 1fr 1fr;
  }

  .profile-layout {
    grid-template-columns: 1fr;
  }

  .activity-panel,
  .tag-card {
    grid-column: 1;
  }
}
@media (width <= 520px) {
  .profile-hero {
    display: grid;
  }

  .profile-value {
    padding: 12px 0 0;
    border-top: 1px solid var(--el-border-color-lighter);
    border-left: 0;
  }

  .profile-fields dl {
    grid-template-columns: 1fr;
  }

  .profile-fields .field-wide {
    grid-column: 1;
  }

  .activity-heading {
    display: grid;
  }

  .activity-summary {
    flex-wrap: wrap;
  }
}
</style>
