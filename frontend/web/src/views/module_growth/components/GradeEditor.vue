<script setup lang="ts">
import { computed } from "vue";
import { metricLabels, type GradePolicy, type Metric } from "@/api/module_growth";
import RuleTag from "./RuleTag.vue";
const model = defineModel<GradePolicy>({ required: true });
const usage: Metric[] = ["net_paid_fen", "active_days", "artifacts", "feedback"];
const metrics = computed(() =>
  (Object.keys(metricLabels) as Metric[]).filter(
    (m) => usage.includes(m) === (model.value.track === "usage")
  )
);
</script>
<template>
  <ElForm label-position="top">
    <section class="growth-form-section">
      <header>评估与降级</header>
      <div class="growth-form-grid">
        <ElFormItem label="统计窗口（天）"
          ><ElInputNumber v-model="model.window_days" :min="7" :max="730"
        /></ElFormItem>
        <ElFormItem label="评估周期"
          ><ElSelect v-model="model.cadence"
            ><ElOption label="每天" value="daily" /><ElOption
              label="每周"
              value="weekly" /><ElOption label="每月" value="monthly" /></ElSelect
        ></ElFormItem>
        <ElFormItem label="连续不达标降级周期"
          ><ElInputNumber v-model="model.downgrade_periods" :min="1" :max="12"
        /></ElFormItem>
      </div>
    </section>
    <section v-if="model.track === 'promotion'" class="growth-form-section">
      <header>数据可信度</header>
      <ElAlert
        title="所有门槛同时满足才升级；样本不足时保留当前等级。"
        type="info"
        :closable="false"
      />
      <div class="growth-form-grid">
        <ElFormItem label="留存最小成熟样本"
          ><ElInputNumber v-model="model.retention_min_samples" :min="1" :max="1000"
        /></ElFormItem>
        <ElFormItem label="合规审核覆盖率（%）"
          ><ElInputNumber v-model="model.compliance_min_coverage" :min="1" :max="100"
        /></ElFormItem>
      </div>
    </section>
    <section v-else class="growth-form-section">
      <header>
        评分维度<ElTag
          :type="
            model.dimensions.reduce((sum, d) => sum + d.weight, 0) === 100 ? 'success' : 'warning'
          "
          >权重 {{ model.dimensions.reduce((sum, d) => sum + d.weight, 0) }} / 100%</ElTag
        >
      </header>
      <ElTable :data="model.dimensions">
        <ElTableColumn label="指标"
          ><template #default="{ row }">{{
            metricLabels[row.metric as Metric]
          }}</template></ElTableColumn
        >
        <ElTableColumn label="权重（%）" width="160"
          ><template #default="{ row }"
            ><ElInputNumber
              v-model="row.weight"
              :min="0"
              :max="100"
              controls-position="right" /></template
        ></ElTableColumn>
        <ElTableColumn label="满分基准" width="180"
          ><template #default="{ row }"
            ><ElInputNumber v-model="row.cap" :min="1" controls-position="right" /></template
        ></ElTableColumn>
      </ElTable>
    </section>
    <section v-for="grade in model.grades" :key="grade.code" class="growth-form-section">
      <header>
        <RuleTag :value="grade.code" /><span>{{ grade.name }}</span
        ><ElText type="info" size="small">{{
          grade.code === "R1" ? "基础等级" : "条件同时满足时升级"
        }}</ElText>
      </header>
      <div class="growth-form-grid">
        <ElFormItem label="等级名称"><ElInput v-model="grade.name" maxlength="32" /></ElFormItem>
        <ElFormItem v-if="model.track === 'usage'" label="最低综合分"
          ><ElInputNumber
            v-model="grade.min_score"
            :disabled="grade.code === 'R1'"
            :min="0"
            :max="100"
        /></ElFormItem>
      </div>
      <div v-for="(condition, index) in grade.conditions" :key="index" class="growth-condition">
        <ElSelect v-model="condition.metric" aria-label="指标"
          ><ElOption
            v-for="metric in metrics"
            :key="metric"
            :label="metricLabels[metric]"
            :value="metric"
        /></ElSelect>
        <ElSelect v-model="condition.operator" aria-label="比较方式"
          ><ElOption label="不低于" value="gte" /><ElOption label="不高于" value="lte"
        /></ElSelect>
        <ElInputNumber
          v-model="condition.value"
          :min="0"
          :max="condition.metric.endsWith('rate') ? 100 : 1000000000"
          aria-label="门槛值"
        />
        <ElButton text type="danger" @click="grade.conditions.splice(index, 1)">移除</ElButton>
      </div>
      <ElButton
        v-if="grade.code !== 'R1'"
        text
        type="primary"
        :disabled="grade.conditions.length >= metrics.length"
        @click="
          grade.conditions.push({
            metric: metrics.find((m) => !grade.conditions.some((c) => c.metric === m))!,
            operator: 'gte',
            value: 1,
          })
        "
        >添加门槛</ElButton
      >
    </section>
  </ElForm>
</template>
