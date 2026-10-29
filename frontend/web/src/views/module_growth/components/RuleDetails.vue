<script setup lang="ts">
import { computed } from "vue";
import {
  eventLabels,
  metricLabels,
  type GrowthRule,
  type GradePolicy,
  type RightsPolicy,
  type IncentivePolicy,
  type RewardAction,
} from "@/api/module_growth";
import RuleTag from "./RuleTag.vue";
const props = defineProps<{ rule: GrowthRule; budgetUsage: { credits: number; cash: number } }>();
const grade = computed(() =>
  ["usage", "promotion"].includes(props.rule.kind) ? (props.rule.config as GradePolicy) : null
);
const rights = computed(() =>
  props.rule.kind === "rights" ? (props.rule.config as RightsPolicy) : null
);
const incentive = computed(() =>
  props.rule.kind === "incentive" ? (props.rule.config as IncentivePolicy) : null
);
const cadence = { daily: "每日", weekly: "每周", monthly: "每月" };
const money = (n: number) => `¥${(n / 100).toLocaleString("zh-CN", { minimumFractionDigits: 2 })}`;
const reward = (a: RewardAction) =>
  a.calculation === "paid_percent"
    ? `净实付 × ${a.percent}%`
    : a.asset === "cash"
      ? money(a.amount)
      : `${Number(a.amount).toLocaleString()} 积分`;
const budgets = computed(() =>
  incentive.value
    ? [
        {
          label: "积分预算",
          total: incentive.value.budget_credits,
          used: props.budgetUsage.credits,
          cash: false,
        },
        {
          label: "现金预算",
          total: incentive.value.budget_cash_fen,
          used: props.budgetUsage.cash,
          cash: true,
        },
      ].filter((b) =>
        incentive.value!.actions.some((a) => a.asset === (b.cash ? "cash" : "credits"))
      )
    : []
);
</script>
<template>
  <div class="rule-details">
    <header class="identity">
      <div class="identity-icon">
        <FaSvgIcon
          :icon="grade ? 'ri:medal-line' : rights ? 'ri:shield-star-line' : 'ri:gift-line'"
        />
      </div>
      <div class="identity-name">
        <h3>{{ rule.name }}</h3>
        <ElText type="info">{{ rule.key }} · V{{ rule.version }}</ElText>
      </div>
      <RuleTag
        :value="rule.status"
        :scheduled="
          rule.status === 'published' &&
          !!rule.effective_at &&
          new Date(rule.effective_at) > new Date()
        "
      />
    </header>
    <div class="meta">
      <span>生效时间</span
      ><strong>{{
        rule.effective_at ? new Date(rule.effective_at).toLocaleString() : "尚未发布"
      }}</strong
      ><span>创建时间</span><strong>{{ new Date(rule.created_time).toLocaleString() }}</strong>
    </div>
    <template v-if="grade">
      <div class="metrics">
        <article>
          <span>统计窗口</span><strong>{{ grade.window_days }} <small>天</small></strong>
        </article>
        <article>
          <span>评估周期</span><strong>{{ cadence[grade.cadence] }}</strong>
        </article>
        <article>
          <span>降级保护</span
          ><strong>{{ grade.downgrade_periods }} <small>个连续不达标周期</small></strong>
        </article>
      </div>
      <section v-if="grade.track === 'usage'" class="panel">
        <h4>评分构成 <ElText type="info" size="small">各维度达到基准后计满分</ElText></h4>
        <div class="dimensions">
          <article v-for="d in grade.dimensions" :key="d.metric">
            <strong>{{ d.weight }}<small>%</small></strong
            ><span>{{ d.metric === "net_paid_fen" ? "净支付金额" : metricLabels[d.metric] }}</span
            ><ElProgress :percentage="d.weight" :show-text="false" :stroke-width="5" /><ElText
              type="info"
              size="small"
              >满分基准 {{ d.metric === "net_paid_fen" ? money(d.cap) : d.cap }}</ElText
            >
          </article>
        </div>
      </section>
      <section class="panel">
        <h4>等级门槛 <ElText type="info" size="small">同一等级内的条件需同时满足</ElText></h4>
        <div class="grade-cards">
          <article v-for="g in grade.grades" :key="g.code" class="grade-card">
            <header>
              <RuleTag :value="g.code" /><strong>{{ g.name }}</strong>
            </header>
            <div v-if="grade.track === 'usage'" class="score">
              {{ g.min_score }}<small>分起</small>
            </div>
            <dl>
              <template v-for="c in g.conditions" :key="c.metric"
                ><dt>{{ metricLabels[c.metric] }}</dt>
                <dd>{{ c.operator === "gte" ? "≥" : "≤" }} {{ c.value }}</dd></template
              >
            </dl>
            <ElText v-if="!g.conditions.length" type="info" size="small"
              >基础等级，无额外门槛</ElText
            >
          </article>
        </div>
      </section>
      <section v-if="grade.track === 'promotion'" class="panel">
        <h4>数据可信度</h4>
        <ElDescriptions :column="2"
          ><ElDescriptionsItem label="留存成熟样本"
            >至少 {{ grade.retention_min_samples }} 人</ElDescriptionsItem
          ><ElDescriptionsItem label="合规核验覆盖率"
            >≥ {{ grade.compliance_min_coverage }}%</ElDescriptionsItem
          ></ElDescriptions
        ><ElText type="info" size="small">样本不足时保留当前等级，不强制降级。</ElText>
      </section>
    </template>
    <template v-if="rights">
      <section class="panel">
        <h4>
          <FaSvgIcon icon="ri:coin-line" />积分权益
          <RuleTag
            :value="rights.gift_enabled ? 'enabled' : 'disabled'"
            :label="rights.gift_enabled ? '转赠已开启' : '转赠未开启'"
          />
        </h4>
        <div class="metrics">
          <article>
            <span>奖励积分有效期</span
            ><strong>{{ rights.credit_valid_days }} <small>天</small></strong>
          </article>
          <article>
            <span>单次转赠最低</span><strong>{{ rights.gift_minimum }} <small>积分</small></strong>
          </article>
          <article>
            <span>每日转赠上限</span
            ><strong>{{ rights.gift_daily_count }} <small>次</small></strong>
          </article>
        </div>
        <ElDescriptions :column="2"
          ><ElDescriptionsItem label="每月可赠额度"
            >月初可赠余额 × {{ rights.gift_monthly_percent }}%</ElDescriptionsItem
          ><ElDescriptionsItem label="奖励积分转赠"
            ><RuleTag
              :value="rights.gift_reward_credits ? 'enabled' : 'disabled'" /></ElDescriptionsItem
          ><ElDescriptionsItem label="接收方资格">{{
            rights.gift_requires_subscription ? "需要有效订阅" : "不限制订阅"
          }}</ElDescriptionsItem></ElDescriptions
        >
      </section>
      <section class="panel">
        <h4>
          <FaSvgIcon icon="ri:wallet-3-line" />推广现金
          <RuleTag
            :value="rights.withdrawal_enabled ? 'enabled' : 'disabled'"
            :label="rights.withdrawal_enabled ? '提现已开启' : '提现未开启'"
          />
        </h4>
        <div class="metrics">
          <article>
            <span>单次提现范围</span
            ><strong
              >{{ money(rights.withdrawal_min_fen)
              }}<small>～ {{ money(rights.withdrawal_max_fen) }}</small></strong
            >
          </article>
          <article>
            <span>每日金额上限</span><strong>{{ money(rights.withdrawal_daily_fen) }}</strong>
          </article>
          <article>
            <span>每月金额上限</span><strong>{{ money(rights.withdrawal_monthly_fen) }}</strong>
          </article>
        </div>
        <ElText type="info"
          >每日最多 {{ rights.withdrawal_daily_count }} 次，提现需财务审核。</ElText
        >
      </section>
    </template>
    <template v-if="incentive">
      <section class="panel">
        <h4>
          触发与适用对象
          <RuleTag
            :value="incentive.mode"
            :label="incentive.mode === 'review' ? '审核后发放' : undefined"
          />
        </h4>
        <div class="trigger">
          <FaSvgIcon icon="ri:flashlight-line" /><strong>{{ eventLabels[incentive.event] }}</strong
          ><RuleTag
            v-if="incentive.feedback_grade"
            :value="incentive.feedback_grade"
            :label="`${incentive.feedback_grade} 级反馈`"
          />
        </div>
        <ElDescriptions :column="2"
          ><ElDescriptionsItem label="用户等级"
            ><span v-if="!incentive.usage_grades.length">不限</span
            ><RuleTag v-for="g in incentive.usage_grades" :key="g" :value="g" /></ElDescriptionsItem
          ><ElDescriptionsItem label="推广等级"
            ><span v-if="!incentive.promotion_grades.length">不限</span
            ><RuleTag
              v-for="g in incentive.promotion_grades"
              :key="g"
              :value="g" /></ElDescriptionsItem
          ><ElDescriptionsItem label="订阅要求">{{
            incentive.require_subscription ? "有效订阅用户" : "不限"
          }}</ElDescriptionsItem></ElDescriptions
        >
        <p v-if="incentive.description" class="description">{{ incentive.description }}</p>
      </section>
      <section class="panel">
        <h4>奖励方案</h4>
        <div class="reward-cards">
          <article v-for="(a, i) in incentive.actions" :key="i">
            <header>
              <ElTag effect="plain">{{ a.recipient === "actor" ? "行为人" : "直接邀请人" }}</ElTag
              ><ElText type="info" size="small">{{
                a.asset === "cash" ? "推广现金" : "可消费积分"
              }}</ElText>
            </header>
            <strong class="reward-value">{{ reward(a) }}</strong>
            <div class="bonuses">
              <span v-for="(value, g) in a.grade_percent" :key="g"
                ><RuleTag :value="String(g)" /> {{ a.calculation === "fixed" ? "+" : ""
                }}{{ value }}%</span
              >
            </div>
            <ElText type="info" size="small"
              >单次上限 {{ a.asset === "cash" ? money(a.maximum) : `${a.maximum} 积分`
              }}<template v-if="a.calculation === 'paid_percent' && a.asset === 'credits'">
                · 每元 {{ a.credits_per_yuan }} 积分</template
              ></ElText
            >
            <p
              v-if="a.calculation === 'fixed' && Object.keys(a.grade_percent).length"
              class="description"
            >
              R 与 A 等级加成相加
            </p>
          </article>
        </div>
      </section>
      <section class="panel">
        <h4>预算与发放控制</h4>
        <div class="budget-cards">
          <article v-for="b in budgets" :key="b.label">
            <header>
              <strong>{{ b.label }}</strong
              ><RuleTag v-if="!b.total" value="draft" label="待配置预算" />
            </header>
            <strong class="reward-value">{{
              b.cash ? money(b.total) : Number(b.total).toLocaleString()
            }}</strong
            ><ElProgress
              :percentage="b.total ? Math.min(100, Math.round((b.used / b.total) * 100)) : 0"
              :status="b.total && b.used >= b.total ? 'warning' : undefined"
            /><ElText type="info" size="small"
              >跨版本累计占用 {{ b.cash ? money(b.used) : b.used }} · 剩余
              {{
                b.cash ? money(Math.max(0, b.total - b.used)) : Math.max(0, b.total - b.used)
              }}</ElText
            >
          </article>
        </div>
        <ElDescriptions :column="2"
          ><ElDescriptionsItem label="每人每日">{{ incentive.daily_limit }} 次</ElDescriptionsItem
          ><ElDescriptionsItem label="每人每月">{{ incentive.monthly_limit }} 次</ElDescriptionsItem
          ><ElDescriptionsItem label="观察期">{{ incentive.observe_days }} 天</ElDescriptionsItem
          ><ElDescriptionsItem label="优先顺序">{{ incentive.priority }}</ElDescriptionsItem
          ><ElDescriptionsItem label="基础奖励叠加"
            ><RuleTag :value="incentive.stackable ? 'enabled' : 'disabled'" /></ElDescriptionsItem
        ></ElDescriptions>
      </section>
    </template>
  </div>
</template>
<style scoped lang="scss">
.rule-details {
  display: grid;
  gap: 20px;
  color: var(--el-text-color-primary);
}
.identity {
  display: flex;
  align-items: center;
  gap: 14px;
}
.identity-icon {
  display: grid;
  place-items: center;
  width: 48px;
  height: 48px;
  border-radius: 12px;
  font-size: 24px;
  color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
}
.identity-name {
  flex: 1;
  min-width: 0;
  h3 {
    margin: 0 0 6px;
    font-size: 18px;
  }
}
.meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 16px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
  strong {
    font-weight: 400;
    color: var(--el-text-color-regular);
  }
}
.panel {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 10px;
  padding: 20px;
  h4 {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 10px;
    margin: 0 0 18px;
    font-size: 15px;
  }
}
.metrics,
.grade-cards,
.dimensions,
.reward-cards,
.budget-cards {
  display: grid;
  gap: 14px;
  grid-template-columns: repeat(3, minmax(0, 1fr));
}
.metrics {
  margin-bottom: 16px;
  article {
    background: var(--el-fill-color-light);
    border-radius: 8px;
    padding: 16px;
  }
  span {
    display: block;
    font-size: 12px;
    color: var(--el-text-color-secondary);
  }
  strong {
    display: block;
    margin-top: 10px;
    font-size: 20px;
  }
  small {
    font-size: 12px;
    font-weight: 400;
  }
}
.dimensions {
  grid-template-columns: repeat(4, minmax(0, 1fr));
  article {
    display: grid;
    gap: 10px;
  }
  strong {
    color: var(--el-color-primary);
    font-size: 24px;
  }
  small {
    font-size: 13px;
  }
  span {
    font-size: 13px;
  }
}
.grade-card,
.reward-cards article,
.budget-cards article {
  padding: 16px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  header {
    display: flex;
    gap: 8px;
    align-items: center;
    justify-content: space-between;
  }
}
.grade-card {
  border-top: 3px solid var(--el-color-primary-light-5);
  dl {
    display: grid;
    grid-template-columns: 1fr auto;
    gap: 12px 6px;
    font-size: 12px;
  }
  dt {
    color: var(--el-text-color-secondary);
  }
  dd {
    margin: 0;
    font-weight: 600;
  }
}
.score {
  font-size: 28px;
  margin: 18px 0;
  small {
    margin-left: 6px;
    font-size: 12px;
    color: var(--el-text-color-secondary);
  }
}
.trigger {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px;
  background: var(--el-color-primary-light-9);
  color: var(--el-color-primary);
  border-radius: 8px;
  margin-bottom: 18px;
}
.reward-cards,
.budget-cards {
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 280px), 1fr));
  margin-bottom: 16px;
}
.reward-value {
  display: block;
  font-size: 24px;
  margin: 18px 0;
}
.bonuses {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 14px;
  margin: 12px 0;
  font-size: 12px;
}
.description {
  color: var(--el-text-color-secondary);
  font-size: 13px;
  line-height: 1.6;
  white-space: pre-wrap;
}
:deep(.el-descriptions__content .el-tag) {
  margin-right: 6px;
}
@media (max-width: 680px) {
  .metrics,
  .grade-cards,
  .reward-cards,
  .budget-cards {
    grid-template-columns: 1fr;
  }
  .dimensions {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .panel {
    padding: 16px;
  }
}
</style>
