<template>
  <div v-if="items.length" class="files">
    <ElLink v-for="item in items" :key="item.url" :href="item.url" target="_blank" type="primary"
      ><FaSvgIcon icon="ri:attachment-2" />{{ item.name }}</ElLink
    >
  </div>
</template>
<script setup lang="ts">
defineProps<{ items: { name: string; url: string; size?: number }[] }>();
</script>
<style scoped>
.files {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}
</style>
