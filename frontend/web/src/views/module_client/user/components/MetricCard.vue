<template>
  <div class="metric-card">
    <span>{{ label }}</span
    ><strong>{{ Number(value || 0).toLocaleString() }}</strong>
  </div>
</template>
<script setup lang="ts">
defineProps<{ label: string; value?: number }>();
</script>
<style scoped>
.metric-card {
  display: grid;
  gap: 6px;
  padding: 14px;
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 10px;
}
.metric-card span {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.metric-card strong {
  font-size: 20px;
  color: var(--el-text-color-primary);
}
</style>
