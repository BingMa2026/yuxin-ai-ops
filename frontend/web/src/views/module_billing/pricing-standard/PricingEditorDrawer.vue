<template>
  <ElDrawer
    :model-value="visible"
    :title="editing ? '编辑价格体系' : '复制为新版本'"
    size="min(1080px, 100vw)"
    class="pricing-editor-drawer"
    :before-close="close"
    :close-on-click-modal="false"
    :close-on-press-escape="!saving"
    :show-close="!saving"
    destroy-on-close
  >
    <template #header>
      <div class="drawer-heading">
        <span class="eyebrow">价格体系 · 全平台模板</span>
        <h2>{{ editing ? "编辑价格体系" : "复制为新版本" }}</h2>
        <p>{{ editing ? form.name : `基于「${sourceName || "当前版本"}」创建独立草稿` }}</p>
      </div>
    </template>
    <div class="editor-layout">
      <nav class="editor-nav" aria-label="价格体系编辑目录">
        <button
          :class="{ active: section === 'basic' }"
          :disabled="saving"
          @click="section = 'basic'"
        >
          <span>基本信息</span><small>名称与版本</small>
        </button>
        <button
          :class="{ active: section === 'rules' }"
          :disabled="saving"
          @click="section = 'rules'"
        >
          <span>通用规则</span><small>兑换、续费与扣减</small>
        </button>
        <div class="nav-heading">
          套餐模板 <span>{{ form.templates.length }}</span>
        </div>
        <div class="package-list">
          <button
            v-for="(item, index) in form.templates"
            :key="index"
            :class="{ active: section === 'template' && activeIndex === index }"
            :aria-current="section === 'template' && activeIndex === index ? 'true' : undefined"
            :disabled="saving"
            @click="selectTemplate(index)"
          >
            <span class="package-name"
              ><b>{{ String(index + 1).padStart(2, "0") }}</b
              >{{ item.name || "未命名套餐" }}</span
            >
            <small
              >¥{{ money(item.one_time_price_fen) }} ·
              {{ item.plan_type === "credit_pack" ? "积分包" : "订阅" }}</small
            >
          </button>
        </div>
        <ElButton class="add-package" :disabled="saving" @click="addTemplate">+ 添加套餐</ElButton>
      </nav>
      <div ref="content" class="editor-content">
        <ElForm label-position="top" :disabled="saving" @submit.prevent>
          <template v-if="section === 'basic'">
            <div class="section-heading">
              <span class="eyebrow">VERSION</span>
              <h3>基本信息</h3>
              <p>用清晰的名称与版本号区分每一套价格配置。</p>
            </div>
            <div class="field-grid">
              <ElFormItem label="版本名称" required
                ><ElInput v-model="form.name" maxlength="64" placeholder="例如：首发价格体系"
              /></ElFormItem>
              <ElFormItem label="版本号" required
                ><ElInput v-model="form.version" maxlength="32" placeholder="例如：MVP-2"
              /></ElFormItem>
            </div>
            <ElFormItem label="版本说明"
              ><ElInput
                v-model="form.description"
                type="textarea"
                :rows="4"
                maxlength="1000"
                show-word-limit
                placeholder="记录本次价格或权益调整，方便后续查阅"
            /></ElFormItem>
            <div class="scope-note">
              套餐模板用于创建刊例，保存不会覆盖已有刊例的价格和权益。{{
                editing ? "版本的发布状态保持不变。" : "新版本保存后为草稿，需要单独发布。"
              }}
            </div>
          </template>
          <template v-else-if="section === 'rules'">
            <div class="section-heading">
              <span class="eyebrow">POLICY</span>
              <h3>通用规则</h3>
              <p>统一设置此版本的基础计价和积分使用规则。</p>
            </div>
            <ElAlert
              v-if="editing && status === 'published'"
              title="已发布版本的通用规则会影响使用它的业务；积分扣减顺序全平台生效。"
              type="warning"
              :closable="false"
              class="policy-alert"
            />
            <div class="field-grid">
              <ElFormItem label="每 1 元兑换积分"
                ><ElInputNumber
                  v-model="form.credits_per_yuan"
                  @change="changeCreditRate"
                  :min="1"
                  :max="1000000"
                  :precision="0"
                  controls-position="right"
              /></ElFormItem>
              <ElFormItem label="默认订阅周期（天）"
                ><ElInputNumber
                  v-model="form.subscription_cycle_days"
                  :min="1"
                  :max="3650"
                  :precision="0"
                  controls-position="right"
              /></ElFormItem>
              <ElFormItem label="续费折扣系数"
                ><ElInputNumber
                  v-model="form.renewal_discount_rate"
                  :min="0.01"
                  :max="1"
                  :step="0.05"
                  controls-position="right"
                /><small class="field-hint">0.9 表示 9 折</small></ElFormItem
              >
              <ElFormItem label="默认目标毛利率（%）"
                ><ElInputNumber
                  v-model="form.margin_baseline"
                  :min="0"
                  :max="99"
                  controls-position="right"
              /></ElFormItem>
              <ElFormItem label="毛利率安全线（%）"
                ><ElInputNumber
                  v-model="form.margin_floor"
                  :min="0"
                  :max="99"
                  controls-position="right"
              /></ElFormItem>
            </div>
            <div class="subheading">
              <h4>积分扣减顺序</h4>
              <p>从上到下依次扣减，可用箭头调整优先级。</p>
            </div>
            <div
              v-for="(account, index) in form.account_priority"
              :key="account"
              class="priority-row"
            >
              <span class="priority-number">{{ index + 1 }}</span
              ><span>{{ accountLabel(account) }}</span>
              <div>
                <ElButton
                  text
                  :disabled="index === 0"
                  :aria-label="`上移${accountLabel(account)}`"
                  @click="moveAccount(index, -1)"
                  >↑</ElButton
                ><ElButton
                  text
                  :disabled="index === form.account_priority.length - 1"
                  :aria-label="`下移${accountLabel(account)}`"
                  @click="moveAccount(index, 1)"
                  >↓</ElButton
                >
              </div>
            </div>
          </template>
          <template v-else-if="item">
            <div class="section-heading package-heading">
              <div>
                <span class="eyebrow"
                  >套餐 {{ activeIndex + 1 }} / {{ form.templates.length }}</span
                >
                <h3>{{ item.name || "未命名套餐" }}</h3>
                <p>修改此套餐的定价、积分与服务权益。</p>
              </div>
              <ElButton text type="danger" @click="removeTemplate">移除套餐</ElButton>
            </div>
            <div class="package-summary">
              <div>
                <small>首购价格</small><strong>¥{{ money(item.one_time_price_fen) }}</strong>
              </div>
              <div>
                <small>{{ item.entitlement_kind === "duration" ? "订阅天数" : "总积分" }}</small
                ><strong>{{
                  (item.entitlement_kind === "duration"
                    ? item.billing_period_days
                    : item.total_credits || 0
                  ).toLocaleString()
                }}</strong>
              </div>
              <div>
                <small>有效期</small
                ><strong
                  >{{
                    item.entitlement_kind === "duration"
                      ? item.billing_period_days
                      : item.credit_valid_days
                  }}
                  <em>天</em></strong
                >
              </div>
            </div>
            <ElTabs v-model="packageTab" class="package-tabs">
              <ElTabPane label="套餐与价格" name="price">
                <div class="field-grid">
                  <ElFormItem label="套餐名称" required
                    ><ElInput v-model="item.name" maxlength="64"
                  /></ElFormItem>
                  <ElFormItem label="套餐编码" required
                    ><ElInput v-model="item.code" maxlength="64" placeholder="例如 starter"
                  /></ElFormItem>
                  <ElFormItem label="权益类型">
                    <ElSelect
                      :model-value="item.entitlement_kind || 'credits'"
                      @change="changeEntitlement"
                    >
                      <ElOption label="含 token 费用" value="credits" />
                      <ElOption label="token 自费" value="duration" />
                    </ElSelect>
                  </ElFormItem>
                  <ElFormItem v-if="item.entitlement_kind !== 'duration'" label="套餐类型"
                    ><ElSelect v-model="item.plan_type" @change="changePlanType"
                      ><ElOption label="订阅套餐" value="subscription" /><ElOption
                        label="流量积分包"
                        value="credit_pack" /></ElSelect
                  ></ElFormItem>
                  <ElFormItem
                    v-if="item.plan_type === 'subscription' && item.entitlement_kind !== 'duration'"
                    label="套餐等级"
                    ><ElSelect v-model="item.tier_code"
                      ><ElOption label="体验版 / Free" value="free" /><ElOption
                        label="基础版"
                        value="starter" /><ElOption label="专业版" value="professional" /><ElOption
                        label="企业版"
                        value="enterprise" /></ElSelect
                  ></ElFormItem>
                  <ElFormItem label="首购价（元）"
                    ><ElInputNumber
                      :model-value="item.one_time_price_fen / 100"
                      :min="0"
                      :precision="2"
                      controls-position="right"
                      @update:model-value="changePrice"
                  /></ElFormItem>
                  <ElFormItem label="续费价（元）"
                    ><ElInputNumber
                      :model-value="item.recurring_price_fen / 100"
                      :min="0"
                      :precision="2"
                      controls-position="right"
                      @update:model-value="
                        item.recurring_price_fen = Math.round(($event || 0) * 100)
                      "
                  /></ElFormItem>
                  <ElFormItem label="权益周期（天）"
                    ><ElInputNumber
                      v-model="item.billing_period_days"
                      :min="1"
                      :max="3650"
                      :precision="0"
                      controls-position="right"
                  /></ElFormItem>
                  <ElFormItem v-if="item.plan_type === 'subscription'" label="等级顺序"
                    ><ElInputNumber
                      v-model="item.tier_order"
                      :min="0"
                      :max="999"
                      :precision="0"
                      controls-position="right"
                  /></ElFormItem>
                </div>
              </ElTabPane>
              <ElTabPane
                v-if="item.entitlement_kind !== 'duration'"
                label="积分释放"
                name="credits"
              >
                <div class="field-grid">
                  <ElFormItem label="总积分" required
                    ><ElInputNumber
                      v-model="item.total_credits"
                      @change="rebalanceCurrent"
                      :min="Math.max(1, item.release_plan.length)"
                      :precision="0"
                      controls-position="right" /></ElFormItem
                  ><ElFormItem label="积分有效期（天）"
                    ><ElInputNumber
                      v-model="item.credit_valid_days"
                      :min="1"
                      :max="3650"
                      :precision="0"
                      controls-position="right"
                  /></ElFormItem>
                </div>
                <div class="release-heading">
                  <h4>释放批次</h4>
                  <ElButton
                    link
                    type="primary"
                    :disabled="item.total_credits <= item.release_plan.length"
                    @click="addRelease"
                    >+ 添加批次</ElButton
                  >
                </div>
                <div
                  v-for="(release, index) in item.release_plan"
                  :key="index"
                  class="release-card"
                >
                  <div class="release-title">
                    <strong>第 {{ index + 1 }} 批</strong
                    ><ElButton
                      text
                      type="danger"
                      :disabled="item.release_plan.length === 1"
                      @click="removeRelease(index)"
                      >移除</ElButton
                    >
                  </div>
                  <div class="release-grid">
                    <ElFormItem label="领取后第几天"
                      ><ElInputNumber
                        v-model="release.offset_day"
                        :min="0"
                        :max="3650"
                        :precision="0"
                        controls-position="right" /></ElFormItem
                    ><ElFormItem label="释放积分"
                      ><ElInputNumber
                        v-model="release.amount"
                        :min="1"
                        :precision="0"
                        controls-position="right" /></ElFormItem
                    ><ElFormItem label="积分账户"
                      ><ElSelect v-model="release.account_type"
                        ><ElOption
                          v-for="account in accounts"
                          :key="account.value"
                          :label="account.label"
                          :value="account.value" /></ElSelect
                    ></ElFormItem>
                  </div>
                </div>
                <div
                  class="release-total"
                  :class="{ invalid: releaseTotal !== item.total_credits }"
                >
                  已分配 {{ releaseTotal.toLocaleString() }} /
                  {{ (item.total_credits || 0).toLocaleString() }} 积分
                  <span>{{
                    releaseTotal === item.total_credits ? "分配完成" : "请调整至与总积分一致"
                  }}</span>
                </div>
              </ElTabPane>
              <ElTabPane label="服务权益" name="benefits">
                <ElFormItem label="权益说明"
                  ><ElSelect
                    v-model="item.benefits"
                    multiple
                    filterable
                    allow-create
                    default-first-option
                    placeholder="输入一项权益后按回车添加"
                /></ElFormItem>
                <ElFormItem label="续费与取消说明"
                  ><ElInput v-model="item.renewal_rule" type="textarea" :rows="3"
                /></ElFormItem>
                <div class="subscription-rule">
                  <div>
                    <h4>需要有效订阅</h4>
                    <p>开启后，用户需先拥有有效订阅才能购买。</p>
                  </div>
                  <ElSwitch
                    v-model="item.requires_active_subscription"
                    :disabled="
                      item.plan_type === 'credit_pack' || item.entitlement_kind === 'duration'
                    "
                  />
                </div>
              </ElTabPane>
            </ElTabs>
          </template>
          <ElEmpty v-else description="添加一个套餐开始配置" />
        </ElForm>
      </div>
    </div>
    <template #footer
      ><div class="drawer-footer">
        <span
          >{{ form.templates.length }} 个套餐 ·
          {{ editing ? "保存到当前版本" : "保存后为草稿" }}</span
        >
        <div>
          <ElButton :disabled="saving" @click="close()">取消</ElButton
          ><ElButton type="primary" :loading="saving" @click="$emit('save')">{{
            editing ? "保存修改" : "保存草稿"
          }}</ElButton>
        </div>
      </div></template
    >
  </ElDrawer>
</template>

<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import type { PricingVersionForm } from "@/api/module_billing";
import { rebalanceReleases, updateDefaultCredits, updatePriceCredits } from "./credit-allocation";
const props = defineProps<{
  visible: boolean;
  editing: boolean;
  saving: boolean;
  status?: string;
  sourceName?: string;
}>();
const form = defineModel<PricingVersionForm>("form", { required: true });
const emit = defineEmits<{ close: []; save: []; add: [] }>();
const section = ref("basic");
const activeIndex = ref(0);
const packageTab = ref("price");
const content = ref<HTMLElement>();
let original = "";
const item = computed(() => form.value.templates[activeIndex.value]);
const accounts = [
  { label: "活动赠送", value: "activity_reward" },
  { label: "当期权益", value: "current_cycle" },
  { label: "月度储备", value: "monthly_reserve" },
  { label: "流量积分包", value: "traffic_pack" },
  { label: "企业共享", value: "enterprise_pool" },
  { label: "人工调整", value: "manual" },
];
const accountLabel = (value: string) => accounts.find((a) => a.value === value)?.label || value;
const money = (value: number) => ((value || 0) / 100).toFixed(2);
const releaseTotal = computed(
  () => item.value?.release_plan.reduce((sum, r) => sum + (r.amount || 0), 0) || 0
);
watch(
  () => props.visible,
  (visible) => {
    if (visible) {
      original = JSON.stringify(form.value);
      section.value = "basic";
      activeIndex.value = 0;
      packageTab.value = "price";
    }
  }
);
watch([section, activeIndex, packageTab], async () => {
  await nextTick();
  content.value?.scrollTo({ top: 0 });
});
function selectTemplate(index: number) {
  activeIndex.value = index;
  section.value = "template";
}
function addTemplate() {
  emit("add");
  selectTemplate(form.value.templates.length - 1);
  packageTab.value = "price";
}
async function removeTemplate() {
  if (!item.value) return;
  try {
    await ElMessageBox.confirm(
      `从模板中移除「${item.value.name || "未命名套餐"}」？保存后生效，已有刊例不受影响。`,
      "移除套餐",
      { type: "warning", confirmButtonText: "移除", cancelButtonText: "取消" }
    );
  } catch {
    return;
  }
  form.value.templates.splice(activeIndex.value, 1);
  activeIndex.value = Math.max(0, Math.min(activeIndex.value, form.value.templates.length - 1));
}
function moveAccount(index: number, offset: number) {
  const target = index + offset;
  if (target < 0 || target >= form.value.account_priority.length) return;
  const values = form.value.account_priority;
  [values[index], values[target]] = [values[target]!, values[index]!];
}
function changeEntitlement(value: "credits" | "duration") {
  if (!item.value) return;
  Object.assign(item.value, {
    entitlement_kind: value,
    plan_type: "subscription",
    requires_active_subscription: false,
    tier_code: undefined,
    tier_order: 0,
  });
  item.value.total_credits = value === "duration" ? 0 : Math.max(1000, item.value.total_credits);
  item.value.release_plan =
    value === "duration"
      ? []
      : [{ offset_day: 0, amount: item.value.total_credits, account_type: "current_cycle" }];
  packageTab.value = "price";
}
function changePlanType() {
  if (item.value?.plan_type === "credit_pack") {
    item.value.requires_active_subscription = true;
    item.value.tier_code = undefined;
    item.value.tier_order = 0;
  }
}
function addRelease() {
  if (!item.value || item.value.total_credits <= item.value.release_plan.length) return;
  item.value.release_plan.push({
    offset_day: 0,
    amount: 1,
    account_type: item.value.plan_type === "credit_pack" ? "traffic_pack" : "current_cycle",
  });
  rebalanceCurrent();
}
function removeRelease(index: number) {
  if (!item.value || item.value.release_plan.length <= 1) return;
  item.value.release_plan.splice(index, 1);
  rebalanceCurrent();
}
function rebalanceCurrent() {
  if (item.value && !rebalanceReleases(item.value))
    ElMessage.warning("总积分必须是整数，且不能少于批次数量");
}
function changePrice(value: number | undefined) {
  if (!item.value || value === undefined) return;
  item.value.one_time_price_fen = Math.round(value * 100);
  if (!updatePriceCredits(item.value, form.value.credits_per_yuan))
    ElMessage.warning("按价格计算的总积分不足，请调整总积分或减少批次");
}
function changeCreditRate(value: number | undefined, oldValue: number | undefined) {
  if (value && oldValue) updateDefaultCredits(form.value.templates, oldValue, value);
}
async function close() {
  if (props.saving) return;
  if (JSON.stringify(form.value) !== original) {
    try {
      await ElMessageBox.confirm("尚有未保存的修改，确定关闭？", "放弃修改", {
        confirmButtonText: "放弃修改",
        cancelButtonText: "继续编辑",
        type: "warning",
      });
    } catch {
      return;
    }
  }
  emit("close");
}
function revealTemplate(index: number, tab = "price") {
  selectTemplate(index);
  packageTab.value = tab;
}
defineExpose({ revealTemplate });
</script>

<style scoped>
.drawer-heading h2 {
  margin: 5px 0 6px;
  font-size: 23px;
  color: var(--el-text-color-primary);
}

.drawer-heading p,
.section-heading p,
.subheading p,
.subscription-rule p {
  margin: 0;
  font-size: 12px;
  line-height: 1.7;
  color: var(--el-text-color-secondary);
}

.eyebrow {
  font-size: 11px;
  font-weight: 600;
  color: var(--el-text-color-secondary);
  letter-spacing: 1px;
}

.editor-layout {
  display: grid;
  grid-template-columns: 226px minmax(0, 1fr);
  height: 100%;
  min-height: 0;
  border-top: 1px solid var(--el-border-color-lighter);
}

.editor-nav {
  display: flex;
  flex-direction: column;
  gap: 5px;
  min-height: 0;
  padding: 20px 14px;
  background: var(--el-fill-color-extra-light);
  border-right: 1px solid var(--el-border-color-lighter);
}

.editor-nav button:not(.el-button) {
  display: grid;
  flex-shrink: 0;
  gap: 5px;
  width: 100%;
  padding: 9px 13px;
  font-size: 13px;
  color: var(--el-text-color-primary);
  text-align: left;
  cursor: pointer;
  background: transparent;
  border: 1px solid transparent;
  border-radius: 8px;
}

.editor-nav button:not(.el-button):hover {
  background: var(--el-fill-color);
}

.editor-nav button.active:not(.el-button) {
  color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
  border-color: var(--el-color-primary-light-7);
}

.editor-nav button:focus-visible {
  outline: 2px solid var(--el-color-primary);
  outline-offset: 1px;
}

.editor-nav small {
  font-size: 11px;
  color: var(--el-text-color-secondary);
}

.package-name {
  display: flex;
  gap: 9px;
  align-items: baseline;
  overflow-wrap: anywhere;
}

.package-name b {
  font-size: 10px;
  font-variant-numeric: tabular-nums;
  color: var(--el-text-color-secondary);
}

.package-list {
  min-height: 70px;
  overflow-y: auto;
}

.package-list button {
  margin-bottom: 4px;
}

.nav-heading {
  display: flex;
  justify-content: space-between;
  padding: 20px 13px 8px;
  font-size: 11px;
  color: var(--el-text-color-secondary);
}

.add-package {
  flex-shrink: 0;
  width: 100%;
  margin-top: 7px;
}

.editor-content {
  min-width: 0;
  padding: 32px;
  overflow-y: auto;
}

.section-heading {
  margin-bottom: 26px;
}

.section-heading h3 {
  margin: 7px 0 8px;
  font-size: 22px;
  color: var(--el-text-color-primary);
}

.package-heading {
  display: flex;
  gap: 12px;
  align-items: center;
  justify-content: space-between;
}

.field-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 22px;
}

.editor-content :deep(.el-input-number),
.editor-content :deep(.el-select) {
  width: 100%;
}

.editor-content :deep(.el-form-item) {
  margin-bottom: 22px;
}

.editor-content :deep(.el-form-item__label) {
  font-size: 12px;
}

.scope-note {
  padding: 16px 18px;
  font-size: 12px;
  line-height: 1.8;
  color: var(--el-text-color-secondary);
  background: var(--el-fill-color-extra-light);
  border-left: 3px solid var(--el-color-primary-light-5);
  border-radius: 4px;
}

.field-hint {
  font-size: 11px;
  color: var(--el-text-color-secondary);
}

.subheading {
  margin: 16px 0;
}

h4 {
  margin: 0 0 5px;
  font-size: 13px;
  color: var(--el-text-color-primary);
}

.priority-row {
  display: flex;
  gap: 12px;
  align-items: center;
  padding: 7px 12px;
  font-size: 13px;
  border-bottom: 1px solid var(--el-border-color-lighter);
}

.priority-row > div {
  margin-left: auto;
}

.priority-number {
  font-variant-numeric: tabular-nums;
  color: var(--el-text-color-placeholder);
}

.package-summary {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
  padding: 18px 20px;
  margin-bottom: 22px;
  background: var(--el-fill-color-extra-light);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 10px;
}

.package-summary > div {
  display: grid;
  gap: 7px;
  min-width: 0;
}

.package-summary small {
  font-size: 11px;
  color: var(--el-text-color-secondary);
}

.package-summary strong {
  font-size: 20px;
  font-weight: 600;
  overflow-wrap: anywhere;
}

.package-summary em {
  font-size: 12px;
  font-style: normal;
  font-weight: 400;
}

.package-tabs :deep(.el-tabs__header) {
  margin-bottom: 24px;
}

.release-heading,
.release-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.release-card {
  padding: 12px 16px 0;
  margin-bottom: 12px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 10px;
}

.release-title {
  margin-bottom: 8px;
  font-size: 12px;
}

.release-grid {
  display: grid;
  grid-template-columns: 1fr 1fr 1.3fr;
  gap: 12px;
}

.release-total {
  padding: 12px;
  font-size: 12px;
  color: var(--el-color-success);
  background: var(--el-fill-color-extra-light);
  border-radius: 6px;
}

.release-total span {
  display: block;
  margin-top: 5px;
}

.release-total.invalid {
  color: var(--el-color-danger);
}

.subscription-rule {
  display: flex;
  gap: 20px;
  align-items: center;
  justify-content: space-between;
  padding-top: 20px;
  border-top: 1px solid var(--el-border-color-lighter);
}

.drawer-footer {
  display: flex;
  gap: 12px;
  align-items: center;
  justify-content: space-between;
}

.drawer-footer > span {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.policy-alert {
  margin-bottom: 22px;
}
@media (width <= 700px) {
  .editor-layout {
    grid-template-columns: 160px minmax(0, 1fr);
  }

  .editor-nav {
    padding: 12px 8px;
  }

  .editor-content {
    padding: 20px 16px;
  }

  .field-grid,
  .release-grid {
    grid-template-columns: 1fr;
  }

  .package-summary {
    grid-template-columns: 1fr;
  }

  .package-heading {
    flex-direction: column;
    align-items: start;
  }

  .drawer-footer > span {
    display: none;
  }

  .drawer-footer {
    justify-content: flex-end;
  }
}
</style>

<style>
.pricing-editor-drawer .el-drawer__header {
  padding: 20px 24px;
  margin-bottom: 0;
}

.pricing-editor-drawer .el-drawer__body {
  padding: 0;
  overflow: hidden;
}

.pricing-editor-drawer .el-drawer__footer {
  padding: 16px 24px;
  border-top: 1px solid var(--el-border-color-lighter);
}
</style>
