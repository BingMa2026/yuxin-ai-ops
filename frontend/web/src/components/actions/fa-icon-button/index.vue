<!-- 按钮组件 -->
<template>
  <button
    type="button"
    :aria-label="label"
    :title="label"
    class="fa-icon-button size-8.5 inline-flex items-center justify-center cursor-pointer text-g-600 dark:text-g-800 text-xl rounded transition duration-300 hover:bg-hover-color"
    :class="{ 'rounded-full': circle }"
  >
    <FaSvgIcon :icon="icon"></FaSvgIcon>
    <slot></slot>
  </button>
</template>

<script lang="ts" setup>
defineOptions({ name: "FaIconButton" });

interface Props {
  /** 图标名称 */
  icon: string;
  /** 图标按钮的可访问名称 */
  label: string;
  /** 圆角按钮 */
  circle?: boolean;
}

withDefaults(defineProps<Props>(), {});
</script>

<style lang="scss" scoped>
.fa-icon-button {
  padding: 0;
  background: transparent;
  border: 0;

  &:focus-visible {
    outline: 2px solid var(--el-color-primary);
    outline-offset: 2px;
  }

  &:hover :deep(.fa-svg-icon) {
    color: var(--el-color-primary);
  }
}
</style>
