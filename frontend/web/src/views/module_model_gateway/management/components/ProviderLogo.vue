<template>
  <span class="brand-logo" :class="{ large }" :title="name">
    <img v-if="source" :src="source" :alt="name" />
    <span v-else>{{ name.slice(0, 2) }}</span>
  </span>
</template>
<script setup lang="ts">
const props = defineProps<{ code: string; name: string; large?: boolean }>();
const logos = import.meta.glob("../assets/provider-logos/*.svg", {
  eager: true,
  query: "?url",
  import: "default",
}) as Record<string, string>;
const source = computed(
  () => logos[`../assets/provider-logos/${props.code === "zhipu" ? "zai" : props.code}.svg`]
);
</script>
<style scoped>
.brand-logo {
  display: grid;
  place-items: center;
  flex-shrink: 0;
  width: 38px;
  height: 38px;
  border-radius: 10px;
  background: var(--el-color-white);
  color: var(--el-color-primary);
  font-size: 12px;
}
.brand-logo img {
  width: 26px;
  height: 26px;
  object-fit: contain;
}
.brand-logo.large {
  width: 52px;
  height: 52px;
  border-radius: 12px;
}
.brand-logo.large img {
  width: 36px;
  height: 36px;
}
</style>
