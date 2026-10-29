<!-- 表格按钮 -->
<template>
  <button
    type="button"
    :aria-label="label"
    :title="label"
    :disabled="disabled"
    :class="[
      'inline-flex size-8 shrink-0 items-center justify-center border-0 p-0 text-sm rounded-md align-middle transition-all duration-200 hover-btn',
      disabled ? 'cursor-not-allowed opacity-40' : 'cursor-pointer',
      buttonClass,
    ]"
    :style="{ backgroundColor: buttonBgColor, color: iconColor }"
    @click="handleClick"
  >
    <FaSvgIcon :icon="iconContent" />
  </button>
</template>

<script setup lang="ts">
import { computed } from "vue";

defineOptions({ name: "FaButtonTable" });

interface Props {
  /** 按钮类型 */
  type?: "add" | "edit" | "delete" | "view" | "custom";
  /** 按钮图标 */
  icon?: string;
  /** 按钮样式类 */
  iconClass?: string;
  /** icon 颜色 */
  iconColor?: string;
  /** 按钮背景色 */
  buttonBgColor?: string;
  /** 可访问名称及原生悬浮提示 */
  label?: string;
  /** 是否禁用 */
  disabled?: boolean;
}

const props = withDefaults(defineProps<Props>(), {});

interface Emits {
  click: [];
}

const emit = defineEmits<Emits>();

// 默认按钮配置
const defaultButtons = {
  add: { icon: "ri:add-fill", class: "bg-theme/12 text-theme" },
  edit: { icon: "ri:pencil-line", class: "bg-secondary/12 text-secondary" },
  delete: { icon: "ri:delete-bin-5-line", class: "bg-error/12 text-error" },
  view: { icon: "ri:eye-line", class: "bg-info/12 text-info" },
  custom: { icon: "ri:settings-3-line", class: "bg-primary/12 text-primary" },
} as const;

// 获取图标内容
const iconContent = computed(() => {
  return props.icon || (props.type ? defaultButtons[props.type]?.icon : "") || "";
});

// 获取按钮样式类
const buttonClass = computed(() => {
  return props.iconClass || (props.type ? defaultButtons[props.type]?.class : "") || "";
});

const handleClick = () => {
  if (props.disabled) return;
  emit("click");
};
</script>
