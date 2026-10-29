<script setup lang="ts">
import { computed } from "vue";
import {
  metricLabels,
  type GradePolicy,
  type GrowthRule,
  type Metric,
  type RightsPolicy,
} from "@/api/module_growth";
import RuleTag from "./RuleTag.vue";
const props = defineProps<{ rule: GrowthRule; unsaved: boolean }>();
const grade = computed(() =>
  props.rule.kind === "usage" || props.rule.kind === "promotion"
    ? (props.rule.config as GradePolicy)
    : null
);
const rights = computed(() =>
  props.rule.kind === "rights" ? (props.rule.config as RightsPolicy) : null
);
const cadence = { daily: "每日", weekly: "每周", monthly: "每月" };
const metrics = computed(() => [
  ...new Set(grade.value?.grades.flatMap((g) => g.conditions.map((c) => c.metric)) || []),
]);
const number = (value: number) =>
  Number.isFinite(Number(value)) ? Number(value).toLocaleString("zh-CN") : "—";
const money = (value: number) =>
  `¥${(Number(value) / 100).toLocaleString("zh-CN", { maximumFractionDigits: 2 })}`;
function metricName(metric: Metric) {
  return metric === "net_paid_fen" ? "净支付金额" : metricLabels[metric].replace("（%）", "");
}
function threshold(g: GradePolicy["grades"][number], metric: Metric) {
  const c = g.conditions.find((c) => c.metric === metric);
  if (!c) return "无额外要求";
  return `${c.operator === "gte" ? "≥" : "≤"} ${metric === "net_paid_fen" ? money(c.value) : number(c.value)}${metric.endsWith("rate") ? "%" : ""}`;
}
const scheduled = computed(
  () =>
    props.rule.status === "published" &&
    !!props.rule.effective_at &&
    new Date(props.rule.effective_at) > new Date()
);
const introductions = {
  usage: "以真实付费、有效活跃、业务成果和采纳反馈评估用户价值。",
  promotion: "按有效邀请、付费转化、留存与合规表现评定推广等级。",
  rights: "积分用于消费，推广现金用于提现；每类资产都有清晰的使用边界。",
  incentive: "",
};
</script>
<template>
  <div class="policy-presentation">
    <header class="presentation-hero">
      <div class="hero-copy">
        <div class="eyebrow">
          <span>{{
            grade ? (grade.track === "usage" ? "用户成长体系" : "推广成长体系") : "资产使用政策"
          }}</span
          ><ElTag v-if="unsaved" type="warning" size="small">未保存预览</ElTag
          ><RuleTag v-else :value="rule.status" :scheduled="scheduled" />
        </div>
        <h2>{{ rule.name || "未命名规则" }}</h2>
        <p>{{ introductions[rule.kind] }}</p>
      </div>
      <div class="hero-emblem" aria-hidden="true">
        <FaSvgIcon
          :icon="
            rights
              ? 'ri:shield-star-line'
              : grade?.track === 'usage'
                ? 'ri:medal-line'
                : 'ri:share-forward-line'
          "
        />
      </div>
    </header>
    <template v-if="grade">
      <div class="policy-strip">
        <span
          >统计近 <b>{{ grade.window_days }}</b> 天</span
        ><span
          ><b>{{ cadence[grade.cadence] }}</b
          >评估</span
        ><span
          >连续 <b>{{ grade.downgrade_periods }}</b> 个周期不达标才降级</span
        ><span class="strip-note">{{
          grade.track === "usage" ? "综合评分与附加门槛同时满足" : "同一档位全部门槛同时满足"
        }}</span>
      </div>
      <div class="level-plans">
        <article
          v-for="(g, index) in grade.grades"
          :key="g.code"
          class="level-plan"
          :class="`tone-${index % 3}`"
        >
          <div class="plan-top">
            <RuleTag :value="g.code" /><span>第 {{ index + 1 }} 档</span>
          </div>
          <div class="plan-name">
            <h3>{{ g.name || g.code }}</h3>
            <FaSvgIcon
              :icon="
                index === 2
                  ? 'ri:vip-crown-line'
                  : index === 1
                    ? 'ri:medal-line'
                    : 'ri:seedling-line'
              "
            />
          </div>
          <div class="plan-highlight">
            <template v-if="grade.track === 'usage'"
              ><strong>{{ number(g.min_score) }}</strong
              ><span>分起<span class="highlight-caption">综合评分门槛</span></span></template
            ><template v-else
              ><strong>{{ g.code }}</strong
              ><span>推广等级<span class="highlight-caption">按实际贡献定级</span></span></template
            >
          </div>
          <div class="plan-requirements">
            <div class="requirements-caption">
              {{ grade.track === "usage" ? "附加条件" : "达标条件" }}
            </div>
            <div v-for="metric in metrics" :key="metric" class="requirement">
              <span>{{ metricName(metric) }}</span
              ><strong :class="{ unrestricted: !g.conditions.some((c) => c.metric === metric) }">{{
                threshold(g, metric)
              }}</strong>
            </div>
            <div v-if="!metrics.length" class="requirement">
              <span>附加门槛</span><strong class="unrestricted">无额外要求</strong>
            </div>
          </div>
          <footer>
            <FaSvgIcon icon="ri:checkbox-circle-line" />{{
              grade.track === "usage" && index === 0
                ? "基础等级，按规则统一评估"
                : "达到本档条件后参与等级评估"
            }}
          </footer>
        </article>
      </div>
      <section v-if="grade.track === 'usage'" class="score-explainer">
        <div class="section-caption">
          <h3>综合分如何组成</h3>
          <span>各维度达到基准时计满分</span>
        </div>
        <div class="score-dimensions">
          <article v-for="d in grade.dimensions" :key="d.metric">
            <div>
              <span>{{ metricName(d.metric) }}</span
              ><strong>{{ d.weight }}<small>%</small></strong>
            </div>
            <ElProgress :percentage="d.weight" :show-text="false" :stroke-width="4" />
            <p>满分基准 {{ d.metric === "net_paid_fen" ? money(d.cap) : number(d.cap) }}</p>
          </article>
        </div>
      </section>
      <div v-else class="assurance">
        <FaSvgIcon icon="ri:shield-check-line" />
        <div>
          <strong>以充分、可信的数据评估</strong>
          <p>
            留存至少 {{ grade.retention_min_samples }} 个成熟样本，合规核验覆盖率至少
            {{ grade.compliance_min_coverage }}%；样本不足时保留当前等级。
          </p>
        </div>
      </div>
    </template>
    <template v-if="rights">
      <div class="policy-strip">
        <span><b>消费积分</b>与<b>推广现金</b>分别记账</span><span>奖励额度由激励规则决定</span
        ><span class="strip-note">流转不改变资产来源与用途</span>
      </div>
      <div class="asset-plans">
        <article class="asset-plan tone-0">
          <div class="asset-heading">
            <div class="asset-icon"><FaSvgIcon icon="ri:coin-line" /></div>
            <div>
              <h3>算力积分</h3>
              <p>用于产品内的模型调用与消费</p>
            </div>
            <ElTag effect="plain">可消费</ElTag>
          </div>
          <div class="asset-highlight">
            <span>奖励积分有效期</span>
            <div>
              <strong>{{ rights.credit_valid_days }}</strong
              ><span>天</span>
            </div>
          </div>
          <div class="asset-permissions">
            <ElTag type="success" effect="light">可消费</ElTag><ElTag type="info">不可提现</ElTag
            ><RuleTag
              :value="rights.gift_enabled ? 'enabled' : 'disabled'"
              :label="rights.gift_enabled ? '转赠已开放' : '转赠未开放'"
            />
          </div>
          <h4>转赠规则</h4>
          <div class="asset-stat-grid">
            <div>
              <strong>{{ number(rights.gift_minimum) }}</strong
              ><span>单次最低积分</span>
            </div>
            <div>
              <strong>{{ rights.gift_daily_count }}<small> 次</small></strong
              ><span>每日最多转赠</span>
            </div>
            <div>
              <strong>{{ rights.gift_monthly_percent }}<small>%</small></strong
              ><span>月初可赠余额上限</span>
            </div>
          </div>
          <div class="asset-notes">
            <p>
              <FaSvgIcon icon="ri:user-received-line" />{{
                rights.gift_requires_subscription ? "接收方须有有效订阅" : "接收方不限制订阅"
              }}
            </p>
            <p>
              <FaSvgIcon icon="ri:gift-line" />{{
                rights.gift_reward_credits ? "允许转赠奖励积分" : "奖励积分不参与转赠"
              }}
            </p>
            <p><FaSvgIcon icon="ri:time-line" />赠送继承原有效期，收到的赠送不能再次转赠</p>
          </div>
          <footer v-if="!rights.gift_enabled">转赠未开放；以上限额在开启后适用</footer>
        </article>
        <article class="asset-plan tone-2">
          <div class="asset-heading">
            <div class="asset-icon"><FaSvgIcon icon="ri:wallet-3-line" /></div>
            <div>
              <h3>推广现金</h3>
              <p>来自直属推荐产生的现金奖励</p>
            </div>
            <ElTag type="warning" effect="plain">独立记账</ElTag>
          </div>
          <div class="asset-highlight">
            <span>单次最低提现</span>
            <div>
              <strong>{{ money(rights.withdrawal_min_fen) }}</strong>
            </div>
          </div>
          <div class="asset-permissions">
            <RuleTag
              :value="rights.withdrawal_enabled ? 'enabled' : 'disabled'"
              :label="rights.withdrawal_enabled ? '提现已开放' : '提现未开放'"
            /><ElTag type="info">不可转赠</ElTag><ElTag type="info">提现须审核</ElTag>
          </div>
          <h4>提现限额</h4>
          <div class="asset-stat-grid">
            <div>
              <strong>{{ money(rights.withdrawal_max_fen) }}</strong
              ><span>单次最高</span>
            </div>
            <div>
              <strong>{{ money(rights.withdrawal_daily_fen) }}</strong
              ><span>每日金额上限</span>
            </div>
            <div>
              <strong>{{ money(rights.withdrawal_monthly_fen) }}</strong
              ><span>每月金额上限</span>
            </div>
          </div>
          <div class="asset-notes">
            <p>
              <FaSvgIcon icon="ri:calendar-check-line" />每日最多提现
              {{ rights.withdrawal_daily_count }} 次
            </p>
            <p><FaSvgIcon icon="ri:shield-check-line" />财务审核后，按支付渠道结果处理</p>
            <p><FaSvgIcon icon="ri:bank-card-line" />发布政策不会直接发起现金打款</p>
          </div>
          <footer v-if="!rights.withdrawal_enabled">提现未开放；以上限额在开启后适用</footer>
        </article>
      </div>
    </template>
    <footer class="presentation-meta">
      <span
        >{{ rule.key || "未设置编号" }} · {{ unsaved ? "当前编辑内容" : `V${rule.version}` }}</span
      ><span>{{
        unsaved
          ? "仅预览效果，不会保存或发布"
          : rule.effective_at
            ? `生效于 ${new Date(rule.effective_at).toLocaleString()}`
            : "尚未发布"
      }}</span>
    </footer>
  </div>
</template>
<style scoped lang="scss">
.policy-presentation {
  color: var(--el-text-color-primary);
  max-width: 1360px;
  margin: 0 auto;
  padding: 4px 16px 8px;
}
.presentation-hero {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 32px;
  padding: 22px 32px;
  background: linear-gradient(110deg, var(--el-color-primary-light-9), var(--el-bg-color));
  border-radius: 16px;
  overflow: hidden;
}
.eyebrow {
  display: flex;
  align-items: center;
  gap: 12px;
  color: var(--el-color-primary);
  font-size: 12px;
  font-weight: 600;
}
.hero-copy h2 {
  margin: 12px 0 8px;
  font-size: clamp(24px, 2.3vw, 32px);
  font-weight: 650;
  letter-spacing: -0.6px;
}
.hero-copy p {
  margin: 0;
  color: var(--el-text-color-secondary);
  line-height: 1.7;
  font-size: 13px;
}
.hero-emblem {
  flex-shrink: 0;
  display: grid;
  place-items: center;
  width: 96px;
  height: 96px;
  font-size: 46px;
  color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
  border: 1px solid var(--el-color-primary-light-7);
  border-radius: 28px;
  transform: rotate(-8deg);
}
.policy-strip {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px 24px;
  margin: 20px 0;
  color: var(--el-text-color-regular);
  font-size: 13px;
  b {
    margin: 0 3px;
    font-weight: 600;
  }
  .strip-note {
    margin-left: auto;
    color: var(--el-text-color-secondary);
    font-size: 12px;
  }
}
.level-plans {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 20px;
}
.tone-0 {
  --plan-color: var(--el-color-primary);
  --plan-tint: var(--el-color-primary-light-9);
  --plan-line: var(--el-color-primary-light-7);
}
.tone-1 {
  --plan-color: var(--el-color-success);
  --plan-tint: var(--el-color-success-light-9);
  --plan-line: var(--el-color-success-light-7);
}
.tone-2 {
  --plan-color: var(--el-color-warning);
  --plan-tint: var(--el-color-warning-light-9);
  --plan-line: var(--el-color-warning-light-7);
}
.level-plan {
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border: 1px solid var(--plan-line);
  border-radius: 14px;
  background: linear-gradient(180deg, var(--plan-tint), var(--el-bg-color) 200px);
  padding: 20px 24px 0;
}
.plan-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  span:last-child {
    font-size: 12px;
    color: var(--el-text-color-secondary);
  }
}
.plan-name {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 14px;
  h3 {
    margin: 0;
    font-size: 20px;
    font-weight: 600;
  }
  :deep(svg) {
    color: var(--plan-color);
    font-size: 24px;
  }
}
.plan-highlight {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 16px 0;
  strong {
    font-size: 46px;
    line-height: 1.1;
    font-weight: 650;
    letter-spacing: -1.5px;
    color: var(--plan-color);
  }
  span {
    font-size: 13px;
  }
  .highlight-caption {
    display: block;
    margin-top: 5px;
    font-size: 11px;
    color: var(--el-text-color-secondary);
  }
}
.plan-requirements {
  border-top: 1px solid var(--el-border-color-lighter);
  padding-top: 14px;
  flex: 1;
}
.requirements-caption {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-bottom: 6px;
}
.requirement {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 12px;
  padding: 8px 0;
  font-size: 13px;
  span {
    color: var(--el-text-color-regular);
  }
  strong {
    white-space: nowrap;
    font-weight: 600;
    font-variant-numeric: tabular-nums;
  }
  .unrestricted {
    color: var(--el-text-color-secondary);
    font-size: 12px;
    font-weight: 400;
  }
}
.level-plan footer {
  display: flex;
  align-items: center;
  gap: 7px;
  border-top: 1px solid var(--el-border-color-lighter);
  margin-top: 14px;
  padding: 14px 0;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  :deep(svg) {
    color: var(--plan-color);
  }
}
.score-explainer {
  margin-top: 22px;
}
.section-caption {
  display: flex;
  align-items: baseline;
  gap: 14px;
  margin-bottom: 14px;
  h3 {
    margin: 0;
    font-size: 14px;
    font-weight: 600;
  }
  span {
    font-size: 12px;
    color: var(--el-text-color-secondary);
  }
}
.score-dimensions {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 28px;
  article > div:first-child {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    margin-bottom: 8px;
    font-size: 13px;
  }
  strong {
    color: var(--el-color-primary);
    font-size: 20px;
  }
  small {
    font-size: 12px;
    margin-left: 2px;
  }
  p {
    color: var(--el-text-color-secondary);
    font-size: 12px;
    margin: 8px 0 0;
  }
}
.assurance {
  display: flex;
  gap: 12px;
  align-items: center;
  background: var(--el-fill-color-light);
  padding: 15px 20px;
  border-radius: 10px;
  margin-top: 20px;
  > :deep(svg) {
    color: var(--el-color-primary);
    font-size: 24px;
    flex-shrink: 0;
  }
  strong {
    font-size: 13px;
    font-weight: 600;
  }
  p {
    font-size: 12px;
    line-height: 1.6;
    color: var(--el-text-color-secondary);
    margin: 5px 0 0;
  }
}
.asset-plans {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 24px;
}
.asset-plan {
  padding: 24px 28px;
  border: 1px solid var(--plan-line);
  border-radius: 14px;
  background: linear-gradient(160deg, var(--plan-tint), var(--el-bg-color) 45%);
  h4 {
    font-size: 14px;
    font-weight: 600;
    margin: 24px 0 16px;
  }
  footer {
    font-size: 12px;
    padding-top: 14px;
    margin-top: 20px;
    border-top: 1px solid var(--el-border-color-lighter);
    color: var(--el-text-color-secondary);
  }
}
.asset-heading {
  display: flex;
  gap: 12px;
  align-items: center;
  h3 {
    font-size: 20px;
    margin: 0 0 6px;
  }
  p {
    font-size: 12px;
    margin: 0;
    color: var(--el-text-color-secondary);
  }
  > .el-tag {
    margin-left: auto;
  }
}
.asset-icon {
  width: 44px;
  height: 44px;
  border-radius: 12px;
  background: var(--plan-tint);
  color: var(--plan-color);
  font-size: 26px;
  display: grid;
  place-items: center;
  flex-shrink: 0;
}
.asset-highlight {
  margin: 26px 0 18px;
  > span {
    font-size: 13px;
    color: var(--el-text-color-secondary);
  }
  > div {
    margin-top: 8px;
  }
  strong {
    color: var(--plan-color);
    font-size: 44px;
    line-height: 1.1;
    font-weight: 650;
    margin-right: 8px;
    letter-spacing: -1px;
  }
}
.asset-permissions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.asset-stat-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
  padding: 18px 0;
  border-block: 1px solid var(--el-border-color-lighter);
  strong {
    font-size: 22px;
    display: block;
    font-weight: 600;
  }
  small {
    font-size: 13px;
  }
  span {
    display: block;
    margin-top: 6px;
    font-size: 12px;
    color: var(--el-text-color-secondary);
  }
}
.asset-notes {
  display: grid;
  gap: 12px;
  margin-top: 20px;
  p {
    margin: 0;
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 12px;
    line-height: 1.5;
    color: var(--el-text-color-regular);
  }
  :deep(svg) {
    flex-shrink: 0;
    color: var(--plan-color);
  }
}
.presentation-meta {
  display: flex;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px 16px;
  margin-top: 20px;
  font-size: 11px;
  color: var(--el-text-color-secondary);
}
@media (max-width: 1000px) {
  .policy-presentation {
    padding: 0;
  }
  .level-plans {
    gap: 12px;
  }
  .level-plan {
    padding: 16px 16px 0;
  }
  .asset-plan {
    padding: 20px;
  }
  .asset-stat-grid strong {
    font-size: 18px;
  }
  .asset-heading {
    flex-wrap: wrap;
  }
}
@media (max-width: 700px) {
  .presentation-hero {
    padding: 20px;
    gap: 12px;
  }
  .hero-emblem {
    width: 52px;
    height: 52px;
    font-size: 28px;
    border-radius: 16px;
  }
  .level-plans,
  .asset-plans {
    grid-template-columns: 1fr;
  }
  .score-dimensions {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 16px;
  }
  .policy-strip .strip-note {
    margin-left: 0;
  }
  .section-caption {
    flex-wrap: wrap;
    gap: 6px;
  }
}
@media (min-width: 701px) and (max-height: 950px) {
  .presentation-hero {
    padding: 16px 24px;
  }
  .hero-copy h2 {
    margin: 8px 0 6px;
    font-size: 28px;
  }
  .hero-emblem {
    width: 72px;
    height: 72px;
    font-size: 36px;
    border-radius: 22px;
  }
  .policy-strip {
    margin: 14px 0;
  }
  .level-plan {
    padding: 16px 20px 0;
  }
  .plan-name {
    margin-top: 10px;
  }
  .plan-name h3 {
    font-size: 18px;
  }
  .plan-highlight {
    padding: 10px 0;
  }
  .plan-highlight strong {
    font-size: 38px;
  }
  .plan-requirements {
    padding-top: 10px;
  }
  .requirement {
    padding: 5px 0;
  }
  .level-plan footer {
    padding: 10px 0;
    margin-top: 10px;
  }
  .assurance {
    margin-top: 14px;
    padding: 12px 16px;
  }
  .presentation-meta {
    margin-top: 14px;
  }
  .asset-plan {
    padding: 20px 24px;
  }
  .asset-highlight {
    margin: 18px 0 14px;
  }
  .asset-highlight strong {
    font-size: 38px;
  }
  .asset-plan h4 {
    margin: 18px 0 12px;
  }
  .asset-stat-grid {
    padding: 14px 0;
  }
  .asset-notes {
    gap: 10px;
    margin-top: 16px;
  }
  .asset-plan footer {
    margin-top: 14px;
    padding-top: 10px;
  }
}
</style>
