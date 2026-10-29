<template>
  <section class="pricing-preview" :aria-busy="busy" v-loading="busy">
    <ElAlert v-if="failed" title="价格加载失败，请刷新重试" type="error" :closable="false" />
    <ElEmpty v-if="!clientAppStore.currentApp && !isDraft" description="请先在顶栏选择客户端" />
    <ElEmpty
      v-else-if="!plans.length && !busy && !failed"
      :description="isDraft ? '此草稿暂无套餐' : '此版本暂无生效中的上架刊例'"
    />
    <template v-for="group in groups" :key="group.type">
      <section v-if="group.items.length" class="plan-group">
        <div class="group-heading">
          <h3>{{ group.title }}</h3>
          <span>{{
            isDraft
              ? "尚未发布"
              : group.type === "subscription"
                ? group.items.every((p) => p.duration)
                  ? "购买 / 续期"
                  : "首购 / 升级"
                : "单次购买"
          }}</span>
        </div>
        <div class="plan-grid" :class="{ 'pack-grid': group.type === 'credit_pack' }">
          <article v-for="plan in group.items" :key="plan.id" class="plan-card">
            <div class="plan-heading">
              <h4>{{ plan.name }}</h4>
              <span v-if="plan.saving > 0" class="offer-label">{{ discountLabel(plan) }}</span>
            </div>
            <div class="price-block">
              <div class="price">
                <span class="currency">¥</span><strong>{{ money(plan.price) }}</strong
                ><span class="period"
                  >/ {{ group.type === "credit_pack" ? "次" : `${plan.days} 天` }}</span
                >
              </div>
              <div class="price-detail">
                <template v-if="plan.saving > 0"
                  ><del>¥{{ money(plan.base) }}</del
                  ><span class="saving">省 ¥{{ money(plan.saving) }}</span></template
                >
                <span v-else>{{
                  plan.price === 0 ? "免费体验" : isDraft ? "模板定价" : "标准价格"
                }}</span>
              </div>
            </div>
            <div class="credit-allocation">
              <strong>{{ plan.duration ? plan.days : plan.credits.toLocaleString() }}</strong
              ><span>{{ plan.duration ? "天使用期" : "算力积分" }}</span>
            </div>
            <div v-if="plan.duration" class="credit-details">
              <span>用户自行配置模型</span><span>购买后累计订阅时间</span>
            </div>
            <div v-else class="credit-details">
              <span>有效期 {{ plan.validDays }} 天</span
              ><span>{{ plan.releaseCount > 1 ? `${plan.releaseCount} 批释放` : "一次发放" }}</span>
            </div>
            <ul v-if="plan.benefits.length" class="benefits">
              <li v-for="benefit in plan.benefits" :key="benefit">
                <span aria-hidden="true">✓</span>{{ benefit }}
              </li>
            </ul>
            <div class="plan-footer">
              <span>{{ isDraft ? "草稿配置" : plan.strategyName || "产品刊例" }}</span
              ><span v-if="plan.requiresSubscription">需有效订阅</span>
            </div>
          </article>
        </div>
      </section>
    </template>
    <p v-if="plans.length && !busy" class="preview-caption">
      {{
        isDraft
          ? "草稿仅供预览，发布不会覆盖已有产品刊例。"
          : "展示此版本面向全部用户的当前售价；专属优惠以用户实际下单为准。"
      }}
    </p>
  </section>
</template>

<script setup lang="ts">
import { computed, onActivated, onDeactivated, onMounted, onUnmounted, ref, watch } from "vue";
import BillingAPI, {
  type CatalogPlan,
  type PricingTemplate,
  type PricingVersion,
} from "@/api/module_billing";
import { useClientAppStore } from "@stores";
import { planBenefits } from "../plan-benefits";
const props = defineProps<{
  version: PricingVersion;
  templates: PricingTemplate[];
  templateLoading: boolean;
}>();
const clientAppStore = useClientAppStore();
const rows = ref<CatalogPlan[]>([]);
const loading = ref(false);
const failed = ref(false);
let requestId = 0;
let active = true;
const isDraft = computed(() => props.version.status === "draft");
const busy = computed(() => (isDraft.value ? props.templateLoading : loading.value));
const money = (value: number) => (value / 100).toFixed(2);
interface PreviewPlan {
  id: number | string;
  name: string;
  type: string;
  price: number;
  base: number;
  saving: number;
  days: number;
  credits: number;
  duration: boolean;
  validDays: number;
  releaseCount: number;
  benefits: string[];
  strategyName?: string;
  requiresSubscription: boolean;
  tierOrder: number;
  order: number;
}
const plans = computed<PreviewPlan[]>(() => {
  if (isDraft.value)
    return props.templates.map((p) => ({
      id: p.id ?? p.code,
      name: p.name,
      type: p.plan_type,
      price: p.one_time_price_fen,
      base: p.one_time_price_fen,
      saving: 0,
      days: p.billing_period_days,
      credits: p.total_credits,
      duration: p.entitlement_kind === "duration",
      validDays: p.credit_valid_days,
      releaseCount: p.release_plan.length,
      benefits: planBenefits(p.benefits),
      requiresSubscription: p.requires_active_subscription,
      tierOrder: p.tier_order,
      order: p.order,
    }));
  return rows.value
    .filter((p) => p.pricing_version_id === props.version.id)
    .map((p) => ({
      id: p.id ?? p.code,
      name: p.name,
      type: p.plan_type,
      price: p.effective_price_fen ?? p.one_time_price_fen,
      base: p.base_price_fen ?? p.one_time_price_fen,
      saving: p.discount_amount_fen ?? 0,
      days: p.benefit_period_days,
      credits: p.total_credits,
      duration: p.entitlement_kind === "duration",
      validDays: p.credit_valid_days,
      releaseCount: p.release_plan.length,
      benefits: planBenefits(p.benefits),
      strategyName: p.strategy_name,
      requiresSubscription: p.requires_active_subscription,
      tierOrder: p.tier_order,
      order: p.order,
    }));
});
const groups = computed(() => [
  {
    type: "subscription",
    title: "含 token 费用 · 订阅套餐",
    items: plans.value
      .filter((p) => p.type === "subscription" && !p.duration)
      .sort((a, b) => a.tierOrder - b.tierOrder || a.order - b.order),
  },
  {
    type: "duration",
    title: "token 自费 · 订阅套餐",
    items: plans.value
      .filter((p) => p.duration)
      .sort((a, b) => a.days - b.days || a.order - b.order),
  },
  {
    type: "credit_pack",
    title: "含 token 费用 · 流量积分包",
    items: plans.value
      .filter((p) => p.type === "credit_pack")
      .sort((a, b) => a.price - b.price || a.order - b.order),
  },
]);
const discountLabel = (plan: PreviewPlan) =>
  plan.base > 0 ? `${Number(((plan.price / plan.base) * 10).toFixed(2))} 折` : "优惠价";
async function load() {
  const id = ++requestId;
  rows.value = [];
  failed.value = false;
  loading.value = false;
  if (!clientAppStore.currentApp || isDraft.value) return;
  loading.value = true;
  try {
    const response = await BillingAPI.preview({ purchase_type: "first" });
    if (id === requestId) rows.value = response.data.data || [];
  } catch {
    if (id === requestId) failed.value = true;
  } finally {
    if (id === requestId) loading.value = false;
  }
}
function refreshOnFocus() {
  if (active) void load();
}
watch(
  () => [clientAppStore.currentApp?.id, props.version.id, props.version.status],
  () => {
    void load();
  },
  { immediate: true }
);
onActivated(() => {
  active = true;
  void load();
});
onDeactivated(() => {
  active = false;
  requestId++;
});
onMounted(() => window.addEventListener("focus", refreshOnFocus));
onUnmounted(() => {
  requestId++;
  window.removeEventListener("focus", refreshOnFocus);
});
defineExpose({ load, loading });
</script>

<style scoped>
.pricing-preview {
  min-height: 320px;
}

.plan-group {
  margin-top: 30px;
}

.group-heading {
  display: flex;
  gap: 12px;
  align-items: baseline;
  margin-bottom: 18px;
}

.group-heading h3 {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
}

.group-heading > span {
  font-size: 11px;
  color: var(--el-text-color-secondary);
}

.plan-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 205px), 1fr));
  gap: 16px;
}

.plan-card {
  display: flex;
  flex-direction: column;
  min-width: 0;
  padding: 22px;
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 14px;
}

.plan-heading {
  display: flex;
  gap: 8px;
  align-items: center;
  justify-content: space-between;
  min-height: 24px;
}

.plan-heading h4 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  overflow-wrap: anywhere;
}

.offer-label {
  flex-shrink: 0;
  padding: 3px 7px;
  font-size: 11px;
  color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
  border-radius: 5px;
}

.price-block {
  margin: 28px 0 24px;
}

.price {
  display: flex;
  flex-wrap: wrap;
  gap: 3px;
  align-items: baseline;
  font-variant-numeric: tabular-nums;
  color: var(--el-text-color-primary);
}

.currency {
  font-size: 18px;
  font-weight: 500;
}

.price strong {
  font-size: 34px;
  font-weight: 600;
  line-height: 1.15;
  letter-spacing: -1px;
}

.period {
  margin-left: 3px;
  font-size: 11px;
  color: var(--el-text-color-secondary);
}

.price-detail {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  min-height: 18px;
  margin-top: 10px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.saving {
  color: var(--el-color-primary);
}

.credit-allocation {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
  align-items: baseline;
  padding-top: 20px;
  border-top: 1px solid var(--el-border-color-lighter);
}

.credit-allocation strong {
  font-size: 21px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.credit-allocation span {
  font-size: 12px;
  color: var(--el-text-color-regular);
}

.credit-details {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 14px;
  margin-top: 8px;
  font-size: 11px;
  color: var(--el-text-color-secondary);
}

.benefits {
  display: grid;
  gap: 13px;
  padding: 0;
  margin: 24px 0;
  font-size: 12px;
  color: var(--el-text-color-regular);
  list-style: none;
}

.benefits li {
  display: flex;
  gap: 9px;
  line-height: 1.6;
  overflow-wrap: anywhere;
}

.benefits li > span {
  color: var(--el-color-primary);
}

.plan-footer {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: space-between;
  padding-top: 24px;
  margin-top: auto;
  font-size: 10px;
  color: var(--el-text-color-secondary);
}

.pack-grid .price-block {
  margin-top: 22px;
}

.preview-caption {
  margin: 24px 0 0;
  font-size: 11px;
  color: var(--el-text-color-secondary);
}
@media (width <= 700px) {
  .plan-card {
    padding: 22px;
  }

  .plan-group {
    margin-top: 24px;
  }
}
</style>
