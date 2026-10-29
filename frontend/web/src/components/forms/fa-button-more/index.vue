<!-- 更多按钮 -->
<template>
  <span class="inline-flex" @click.stop>
    <ElDropdown v-if="visibleItems.length" trigger="click">
      <FaIconButton
        icon="ri:more-2-fill"
        label="更多操作"
        class="size-8! shrink-0 bg-g-200 text-sm dark:bg-g-300/45"
      />
      <template #dropdown>
        <ElDropdownMenu>
          <ElDropdownItem
            v-for="item in visibleItems"
            :key="item.key"
            :disabled="item.disabled"
            @click="handleClick(item)"
          >
            <div class="flex items-center gap-2" :style="{ color: item.color }">
              <FaSvgIcon
                v-if="item.icon"
                :icon="item.icon"
                :style="{ color: item.iconColor ?? item.color }"
              />
              <span>{{ item.label }}</span>
            </div>
          </ElDropdownItem>
        </ElDropdownMenu>
      </template>
    </ElDropdown>
  </span>
</template>

<script setup lang="ts">
import { checkPerm } from "@/utils/checkPerm";
import type { ButtonMoreItem } from "./types";

defineOptions({ name: "FaButtonMore" });

interface Props {
  /** 下拉项列表 */
  list: ButtonMoreItem[];
}

const props = withDefaults(defineProps<Props>(), {});

const visibleItems = computed(() => props.list.filter((item) => checkPerm(item.auth)));

interface Emits {
  click: [item: ButtonMoreItem];
}

const emit = defineEmits<Emits>();

const handleClick = (item: ButtonMoreItem) => {
  emit("click", item);
};
</script>
