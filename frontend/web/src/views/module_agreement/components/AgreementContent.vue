<script setup lang="ts">
import { computed } from "vue";
import DOMPurify from "dompurify";
const props = defineProps<{ title: string; content: string }>();
const html = computed(() => DOMPurify.sanitize(props.content, { USE_PROFILES: { html: true } }));
</script>
<template>
  <article class="agreement-content">
    <h1>{{ title }}</h1>
    <div v-html="html" />
  </article>
</template>
<style scoped>
.agreement-content {
  max-width: 800px;
  margin: auto;
  padding: 24px;
  color: var(--el-text-color-primary);
  line-height: 1.85;
  overflow-wrap: anywhere;
}
.agreement-content h1 {
  font-size: 24px;
  font-weight: 600;
  margin-bottom: 24px;
}
.agreement-content :deep(h2) {
  font-size: 20px;
  font-weight: 600;
  margin: 24px 0 12px;
}
.agreement-content :deep(h3),
.agreement-content :deep(h4) {
  font-size: 17px;
  font-weight: 600;
  margin: 20px 0 10px;
}
.agreement-content :deep(p) {
  margin: 12px 0;
}
.agreement-content :deep(ol) {
  list-style: decimal;
  padding-left: 28px;
}
.agreement-content :deep(ul) {
  list-style: disc;
  padding-left: 28px;
}
.agreement-content :deep(a) {
  color: var(--el-color-primary);
  text-decoration: underline;
}
.agreement-content :deep(table) {
  width: 100%;
  border-collapse: collapse;
  display: block;
  overflow: auto;
}
.agreement-content :deep(td),
.agreement-content :deep(th) {
  border: 1px solid var(--el-border-color);
  padding: 8px 12px;
}
.agreement-content :deep(blockquote) {
  border-left: 3px solid var(--el-border-color);
  padding-left: 16px;
}
</style>
