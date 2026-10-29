<template>
  <div class="empty-panel">
    <FaSvgIcon :icon="icon" /><strong>{{ title }}</strong>
    <p>{{ description }}</p>
  </div>
</template>
<script setup lang="ts">
defineProps<{ icon: string; title: string; description: string }>();
</script>
<style scoped>
.empty-panel {
  display: grid;
  place-items: center;
  min-height: 190px;
  padding: 24px;
  text-align: center;
  color: var(--el-text-color-secondary);
  background: var(--el-fill-color-lighter);
  border: 1px dashed var(--el-border-color);
  border-radius: 12px;
}
.empty-panel > :first-child {
  font-size: 28px;
  color: var(--el-color-primary);
}
.empty-panel strong {
  margin-top: 10px;
  color: var(--el-text-color-primary);
}
.empty-panel p {
  max-width: 420px;
  margin: 6px 0 0;
  font-size: 12px;
  line-height: 1.6;
}
</style>
