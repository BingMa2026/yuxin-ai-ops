<script setup lang="ts">
import { eventLabels, type IncentivePolicy } from "@/api/module_growth";
const model = defineModel<IncentivePolicy>({ required: true });
const grades = ["ungraded", "A1", "A2", "A3"];
</script>
<template>
  <ElForm label-position="top">
    <section class="growth-form-section">
      <header>触发与适用对象</header>
      <div class="growth-form-grid">
        <ElFormItem label="触发事件"
          ><ElSelect v-model="model.event"
            ><ElOption
              v-for="(label, key) in eventLabels"
              :key="key"
              :value="key"
              :label="label" /></ElSelect
        ></ElFormItem>
        <ElFormItem label="执行方式"
          ><ElSelect v-model="model.mode"
            ><ElOption value="review" label="审核后发放" /><ElOption
              value="auto"
              label="自动发放" /><ElOption value="simulation" label="试运行（不入账）" /></ElSelect
        ></ElFormItem>
        <ElFormItem v-if="model.event === 'feedback'" label="反馈价值分级"
          ><ElSelect v-model="model.feedback_grade" clearable
            ><ElOption v-for="g in ['S', 'A', 'B', 'C']" :key="g" :value="g" :label="g" /></ElSelect
        ></ElFormItem>
        <ElFormItem label="要求有效订阅"
          ><ElSwitch v-model="model.require_subscription"
        /></ElFormItem>
        <ElFormItem label="用户等级条件（留空不限）"
          ><ElSelect v-model="model.usage_grades" multiple
            ><ElOption v-for="g in ['R1', 'R2', 'R3']" :key="g" :value="g" :label="g" /></ElSelect
        ></ElFormItem>
        <ElFormItem label="行为人推广等级（留空不限）"
          ><ElSelect v-model="model.promotion_grades" multiple
            ><ElOption
              v-for="g in grades"
              :key="g"
              :value="g"
              :label="g === 'ungraded' ? '未定级' : g" /></ElSelect
        ></ElFormItem>
      </div>
      <ElFormItem label="活动说明（仅展示）"
        ><ElInput v-model="model.description" type="textarea" maxlength="1000" :rows="2"
      /></ElFormItem>
    </section>
    <section class="growth-form-section" v-for="(action, index) in model.actions" :key="index">
      <header>
        <FaSvgIcon icon="ri:gift-line" />奖励方案 {{ index + 1
        }}<ElTag effect="plain">{{ action.recipient === "actor" ? "行为人" : "直接邀请人" }}</ElTag>
      </header>
      <div class="growth-form-grid">
        <ElFormItem label="奖励对象"
          ><ElSelect v-model="action.recipient"
            ><ElOption value="actor" label="行为人" /><ElOption
              value="inviter"
              label="直接邀请人" /></ElSelect
        ></ElFormItem>
        <ElFormItem label="奖励资产"
          ><ElSelect v-model="action.asset"
            ><ElOption value="credits" label="可消费积分" /><ElOption
              value="cash"
              label="推广现金（元）" /></ElSelect
        ></ElFormItem>
        <ElFormItem label="计算方式"
          ><ElSelect v-model="action.calculation"
            ><ElOption
              value="fixed"
              :label="action.asset === 'cash' ? '固定金额（元）' : '固定数量（积分）'" /><ElOption
              v-if="['first_subscription', 'first_traffic'].includes(model.event)"
              value="paid_percent"
              label="按净实付比例" /></ElSelect
        ></ElFormItem>
        <ElFormItem
          v-if="action.calculation === 'fixed'"
          :label="action.asset === 'cash' ? '固定金额（元）' : '固定数量（积分）'"
          ><ElInputNumber
            :model-value="action.asset === 'cash' ? action.amount / 100 : action.amount"
            :min="action.asset === 'cash' ? 0.01 : 1"
            :precision="action.asset === 'cash' ? 2 : 0"
            @update:model-value="
              action.amount = Math.round(($event || 0) * (action.asset === 'cash' ? 100 : 1))
            "
        /></ElFormItem>
        <ElFormItem v-else label="未定级基础比例（%）"
          ><ElInputNumber v-model="action.percent" :min="0" :max="100" :precision="4"
        /></ElFormItem>
        <ElFormItem :label="action.asset === 'cash' ? '单次上限（元）' : '单次上限（积分）'"
          ><ElInputNumber
            :model-value="action.asset === 'cash' ? action.maximum / 100 : action.maximum"
            :min="action.asset === 'cash' ? 0.01 : 1"
            :precision="action.asset === 'cash' ? 2 : 0"
            @update:model-value="
              action.maximum = Math.round(($event || 0) * (action.asset === 'cash' ? 100 : 1))
            "
        /></ElFormItem>
        <ElFormItem
          v-if="action.calculation === 'paid_percent' && action.asset === 'credits'"
          label="每元折合积分"
          ><ElInputNumber v-model="action.credits_per_yuan" :min="1"
        /></ElFormItem>
      </div>
      <div v-if="action.calculation === 'paid_percent'" class="growth-form-grid">
        <ElFormItem v-for="g in ['A1', 'A2', 'A3']" :key="g" :label="`${g}比例（%）`"
          ><ElInputNumber v-model="action.grade_percent[g]" :min="0" :max="100" :precision="4"
        /></ElFormItem>
      </div>
      <template v-else>
        <ElDivider content-position="left">按获奖人等级加成（R 与 A 加成相加）</ElDivider>
        <div class="growth-form-grid">
          <ElFormItem
            v-for="g in ['R1', 'R2', 'R3', 'A1', 'A2', 'A3']"
            :key="g"
            :label="`${g} 加成（%）`"
          >
            <ElInputNumber
              :model-value="action.grade_percent[g] || 0"
              :min="0"
              :max="100"
              :precision="4"
              @update:model-value="action.grade_percent[g] = $event || 0"
            />
          </ElFormItem>
        </div>
      </template>
      <ElButton
        v-if="model.actions.length > 1"
        text
        type="danger"
        @click="model.actions.splice(index, 1)"
        >移除此动作</ElButton
      >
    </section>
    <ElButton
      :disabled="model.actions.length >= 4"
      @click="
        model.actions.push({
          recipient: 'actor',
          asset: 'credits',
          calculation: 'fixed',
          amount: 100,
          percent: 0,
          grade_percent: {},
          credits_per_yuan: 100,
          maximum: 100000,
        })
      "
      >添加奖励动作</ElButton
    >
    <section class="growth-form-section" style="margin-top: 20px">
      <header>预算与发放控制</header>
      <div class="growth-form-grid">
        <ElFormItem label="每人每日次数"
          ><ElInputNumber v-model="model.daily_limit" :min="1"
        /></ElFormItem>
        <ElFormItem label="每人每月次数"
          ><ElInputNumber v-model="model.monthly_limit" :min="1"
        /></ElFormItem>
        <ElFormItem label="观察期（天）"
          ><ElInputNumber v-model="model.observe_days" :min="0" :max="90"
        /></ElFormItem>
        <ElFormItem v-if="model.actions.some((a) => a.asset === 'credits')" label="活动累计积分预算"
          ><ElInputNumber v-model="model.budget_credits" :min="0"
        /></ElFormItem>
        <ElFormItem
          v-if="model.actions.some((a) => a.asset === 'cash')"
          label="活动累计现金预算（元）"
          ><ElInputNumber
            :model-value="model.budget_cash_fen / 100"
            :min="0"
            :precision="2"
            @update:model-value="model.budget_cash_fen = Math.round(($event || 0) * 100)"
        /></ElFormItem>
        <ElFormItem label="优先顺序（越小越先）"
          ><ElInputNumber v-model="model.priority" :min="0"
        /></ElFormItem>
        <ElFormItem label="允许与基础奖励叠加"><ElSwitch v-model="model.stackable" /></ElFormItem>
      </div>
    </section>
  </ElForm>
</template>
