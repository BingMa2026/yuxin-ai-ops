<template>
  <article class="metric-card" :class="`metric-card--${tone}`">
    <div class="metric-card__head">
      <span>{{ label }}</span>
      <FaSvgIcon :icon="icon" />
    </div>
    <strong>{{ value }}</strong>
    <div class="metric-card__foot">
      <span :class="deltaTone">{{ delta }}</span>
      <small>{{ hint }}</small>
    </div>
  </article>
</template>

<script setup lang="ts">
defineProps<{
  label: string;
  value: string;
  delta: string;
  hint: string;
  icon: string;
  tone: "blue" | "green" | "amber" | "violet" | "slate";
  deltaTone: "positive" | "negative" | "neutral";
}>();
</script>

<style scoped>
.metric-card {
  --metric-color: var(--el-color-primary);

  display: grid;
  min-width: 0;
  padding: 17px 18px;
  overflow: hidden;
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 12px;
}

.metric-card--green {
  --metric-color: var(--el-color-success);
}

.metric-card--amber {
  --metric-color: var(--el-color-warning);
}

.metric-card--violet {
  --metric-color: #8b5cf6;
}

.metric-card--slate {
  --metric-color: var(--el-text-color-regular);
}

.metric-card__head,
.metric-card__foot {
  display: flex;
  gap: 8px;
  align-items: center;
  justify-content: space-between;
}

.metric-card__head span,
.metric-card__foot small {
  overflow: hidden;
  text-overflow: ellipsis;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  white-space: nowrap;
}

.metric-card__head > :last-child {
  font-size: 18px;
  color: var(--metric-color);
}

.metric-card > strong {
  margin: 12px 0 10px;
  font-size: clamp(22px, 1.7vw, 28px);
  line-height: 1;
  color: var(--el-text-color-primary);
  letter-spacing: -0.035em;
}

.metric-card__foot > span {
  flex: none;
  font-size: 11px;
  font-weight: 600;
}

.positive {
  color: var(--el-color-success);
}

.negative {
  color: var(--el-color-danger);
}

.neutral {
  color: var(--el-text-color-secondary);
}
</style>
