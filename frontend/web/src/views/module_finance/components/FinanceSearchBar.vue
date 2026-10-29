<script setup lang="ts">
import { computed } from "vue";
import FaSearchBar, { type SearchFormItem } from "@/components/forms/fa-search-bar/index.vue";

defineOptions({ inheritAttrs: false });
const props = defineProps<{ items: SearchFormItem[] }>();
const model = defineModel<Record<string, unknown>>({ default: () => ({}) });
const emit = defineEmits<{ search: [Record<string, unknown>]; reset: [] }>();
const fields = computed(() => props.items.map((item) => ({ ...item, span: 6 })));
</script>

<template>
  <FaSearchBar
    v-bind="$attrs"
    v-model="model"
    class="finance-search"
    :items="fields"
    :span="6"
    label-width="100px"
    @search="emit('search', $event)"
    @reset="emit('reset')"
  />
</template>

<style scoped>
.finance-search {
  container-type: inline-size;
}
.finance-search :deep(.el-row) {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr)) minmax(230px, max-content);
  align-items: start;
}
.finance-search :deep(.el-col) {
  width: auto;
  max-width: none;
  min-width: 0;
}
.finance-search.is-expanded :deep(.el-row) {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}
.finance-search :deep(.el-form-item__label) {
  white-space: nowrap;
}
.finance-search :deep(.el-form-item__content) {
  min-width: 0;
}
.finance-search :deep(.el-input-number),
.finance-search :deep(.el-date-editor) {
  width: 100%;
  min-width: 0;
}
.finance-search :deep(.action-column) {
  grid-column: -2 / -1;
}
.finance-search :deep(.action-buttons-wrapper) {
  flex-wrap: nowrap;
}
@container (max-width: 850px) {
  .finance-search :deep(.el-row),
  .finance-search.is-expanded :deep(.el-row) {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .finance-search :deep(.action-column) {
    grid-column: auto;
  }
}
@container (max-width: 550px) {
  .finance-search :deep(.el-row),
  .finance-search.is-expanded :deep(.el-row) {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
