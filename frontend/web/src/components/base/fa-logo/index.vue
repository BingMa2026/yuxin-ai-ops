<!-- 喻信公司 Logo -->
<template>
  <div class="flex shrink-0 items-center justify-center" :style="logoStyle">
    <img :src="companyLogoUrl" alt="喻信软件" class="block h-full w-full object-contain" />
  </div>
</template>

<script setup lang="ts">
import companyLogoUrl from "@imgs/common/yuxin-logo.png";

defineOptions({ name: "FaLogo" });

interface Props {
  /** logo 大小 */
  size?: number | string;
}

const props = withDefaults(defineProps<Props>(), {
  size: 36,
});

const logoStyle = computed(() => ({
  height: `${props.size}px`,
  aspectRatio: "265 / 121",
}));
</script>
