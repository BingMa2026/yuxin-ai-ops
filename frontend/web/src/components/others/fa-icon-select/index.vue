<!-- 图标选择器 -->
<template>
  <div
    ref="iconSelectRef"
    class="fa-icon-select"
    :style="{ width: typeof props.width === 'number' ? `${props.width}px` : props.width }"
  >
    <ElPopover
      :visible="popoverVisible"
      :width="props.popoverWidth"
      placement="bottom-start"
      trigger="click"
      popper-class="fa-icon-select-popover"
    >
      <template #reference>
        <div class="reference-wrapper" @click="popoverVisible = !popoverVisible">
          <slot>
            <ElInput
              v-model="selectedIcon"
              readonly
              placeholder="点击选择图标"
              class="reference-input"
            >
              <template #prepend>
                <ElIcon v-if="elementIconComp">
                  <component :is="elementIconComp" />
                </ElIcon>
                <FaSvgIcon
                  v-else-if="selectedIcon"
                  :icon="resolveIconForFaSvgIcon(selectedIcon)"
                  class="preview-svg-icon"
                />
                <FaSvgIcon v-else icon="ri:apps-line" class="preview-svg-icon text-placeholder" />
              </template>
              <template #suffix>
                <!-- 清空按钮 -->
                <ElIcon
                  v-if="selectedIcon"
                  class="clear-btn"
                  @click.stop="clearSelectedIcon"
                >
                  <CircleClose />
                </ElIcon>

                <ElIcon
                  class="arrow-icon"
                  :class="{ 'is-open': popoverVisible }"
                  @click.stop="togglePopover"
                >
                  <ArrowDown />
                </ElIcon>
              </template>
            </ElInput>
          </slot>
        </div>
      </template>

      <!-- 图标选择弹窗内容区 -->
      <div ref="popoverContentRef" class="popover-content">
        <ElInput
          v-model="filterText"
          placeholder="输入关键字搜索图标，例如：funds / user / compass / check"
          clearable
          class="mb-2"
          @input="filterIcons"
        />

        <ElTabs v-model="activeTab" @tab-click="handleTabClick">
          <ElTabPane label="SVG 图标" name="svg">
            <ElScrollbar height="260px">
              <ul v-if="filteredSvgIcons.length" class="icon-grid">
                <li
                  v-for="icon in filteredSvgIcons"
                  :key="'svg-' + icon"
                  class="icon-item"
                  :class="{ 'is-active': selectedIcon === icon }"
                  @click="selectIcon(icon)"
                >
                  <ElTooltip :content="icon" placement="bottom" effect="light">
                    <FaSvgIcon :icon="resolveIconForFaSvgIcon(icon)" class="item-icon" />
                  </ElTooltip>
                </li>
              </ul>
              <ElEmpty v-else description="未找到匹配的图标" :image-size="60" />
            </ElScrollbar>
          </ElTabPane>

          <ElTabPane label="Element 图标" name="element">
            <ElScrollbar height="260px">
              <ul v-if="filteredElementIcons.length" class="icon-grid">
                <li
                  v-for="icon in filteredElementIcons"
                  :key="icon"
                  class="icon-item"
                  :class="{ 'is-active': selectedIcon === 'el-icon-' + icon }"
                  @click="selectIcon(icon)"
                >
                  <ElTooltip :content="icon" placement="bottom" effect="light">
                    <ElIcon class="item-icon">
                      <component :is="elementPlusIconsVue[icon]" />
                    </ElIcon>
                  </ElTooltip>
                </li>
              </ul>
              <ElEmpty v-else description="未找到匹配的图标" :image-size="60" />
            </ElScrollbar>
          </ElTabPane>
        </ElTabs>
      </div>
    </ElPopover>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from "vue";
import { CircleClose, ArrowDown } from "@element-plus/icons-vue";
import { onClickOutside } from "@vueuse/core";
import {
  listLocalIconBasenames,
  isIconifyStoredIcon,
  resolveElementPlusIconComponent,
  resolveIconForFaSvgIcon,
} from "@utils";

defineOptions({ name: "FaIconSelect" });

interface Props {
  modelValue?: string;
  width?: string | number;
  popoverWidth?: string | number;
}

const props = withDefaults(defineProps<Props>(), {
  modelValue: "",
  width: "100%",
  popoverWidth: 460,
});

interface Emits {
  "update:modelValue": [value: string];
}

const emit = defineEmits<Emits>();

const iconSelectRef = ref();
const popoverContentRef = ref();
const popoverVisible = ref(false);
const activeTab = ref("svg");

const svgIcons = ref<string[]>([]);
const elementIcons = ref<string[]>([]);
const elementPlusIconsVue = ref<Record<string, any>>({});

async function loadElementIcons() {
  if (elementIcons.value.length > 0) return;
  const icons = await import("@element-plus/icons-vue");
  elementPlusIconsVue.value = icons;
  elementIcons.value = Object.keys(icons);
}

const selectedIcon = defineModel<string | undefined>("modelValue", {
  default: "",
});

const filterText = ref("");
const filteredSvgIcons = ref<string[]>([]);
const filteredElementIcons = ref<string[]>([]);

const elementIconComp = computed(() => {
  return resolveElementPlusIconComponent(selectedIcon.value);
});

function loadIcons() {
  svgIcons.value = listLocalIconBasenames();
  filteredSvgIcons.value = svgIcons.value;
}

async function handleTabClick(tab: any) {
  if (tab.props.name === "element") {
    await loadElementIcons();
    filteredElementIcons.value = elementIcons.value;
  }
}

function filterIcons() {
  const query = filterText.value.trim().toLowerCase();
  if (activeTab.value === "svg") {
    filteredSvgIcons.value = query
      ? svgIcons.value.filter((icon) => icon.toLowerCase().includes(query))
      : svgIcons.value;
  } else {
    filteredElementIcons.value = query
      ? elementIcons.value.filter((icon) => icon.toLowerCase().includes(query))
      : elementIcons.value;
  }
}

function selectIcon(icon: string) {
  const iconName = activeTab.value === "element" ? "el-icon-" + icon : icon;
  emit("update:modelValue", iconName);
  popoverVisible.value = false;
}

function togglePopover() {
  popoverVisible.value = !popoverVisible.value;
}

onClickOutside(
  iconSelectRef,
  () => {
    popoverVisible.value = false;
  },
  { ignore: [popoverContentRef] }
);

function clearSelectedIcon() {
  selectedIcon.value = "";
  emit("update:modelValue", "");
}

onMounted(async () => {
  loadIcons();
  if (selectedIcon.value) {
    const raw = selectedIcon.value.trim();
    const epKey = raw.replace(/^el-icon-/i, "");
    if (raw.startsWith("el-icon-")) {
      await loadElementIcons();
      if (elementIcons.value.includes(epKey)) {
        activeTab.value = "element";
      } else {
        activeTab.value = "svg";
      }
    } else {
      activeTab.value = "svg";
    }
  }
});
</script>

<style scoped>
.fa-icon-select {
  display: inline-block;
  box-sizing: border-box;
}

.reference-wrapper {
  width: 100%;
  cursor: pointer;
}

.reference-input :deep(.el-input__wrapper) {
  cursor: pointer;
}

.preview-svg-icon {
  font-size: 16px;
  color: var(--el-color-primary);
}

.clear-btn {
  margin-right: 6px;
  font-size: 14px;
  color: var(--el-text-color-placeholder);
  transition: color 0.2s;
}

.clear-btn:hover {
  color: var(--el-text-color-secondary);
}

.arrow-icon {
  font-size: 14px;
  color: var(--el-text-color-placeholder);
  transition: transform 0.3s ease;
}

.arrow-icon.is-open {
  transform: rotate(180deg);
}

.popover-content {
  box-sizing: border-box;
  padding: 4px 0;
}

/* 紧凑规整的图标选择网格（8列） */
.icon-grid {
  display: grid;
  grid-template-columns: repeat(8, 1fr);
  gap: 6px;
  padding: 8px 4px 4px;
  margin: 0;
  list-style: none;
}

.icon-item {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 38px;
  padding: 4px;
  cursor: pointer;
  background: var(--el-fill-color-light);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  transition: all 0.2s ease;
}

.icon-item:hover {
  color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
  border-color: var(--el-color-primary);
  transform: scale(1.1);
}

.icon-item.is-active {
  color: #fff;
  background: var(--el-color-primary);
  border-color: var(--el-color-primary);
}

.item-icon {
  font-size: 20px;
}
</style>
