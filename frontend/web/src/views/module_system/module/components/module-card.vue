<template>
  <article class="module-admin-card" :class="`accent-${module.accent}`">
    <span class="accent-line" />
    <header>
      <span class="module-icon"><FaSvgIcon :icon="module.icon || 'ri:apps-line'" /></span>
      <ElTag :type="statusMeta.type" effect="light" size="small">{{ statusMeta.label }}</ElTag>
    </header>
    <div class="module-title">
      <h2>{{ module.name }}</h2>
      <code>{{ module.code }}</code>
    </div>
    <p class="module-description">{{ module.description || "暂无模块说明" }}</p>

    <div class="menu-summary">
      <div class="menu-summary-head">
        <span>菜单预览</span><strong>{{ module.menu_count || 0 }} 项</strong>
      </div>
      <div v-if="module.menu_items?.length" class="menu-list">
        <span v-for="menu in module.menu_items.slice(0, 3)" :key="menu.name">
          <FaSvgIcon :icon="menu.icon || 'ri:menu-line'" />{{ menu.name }}
        </span>
      </div>
      <span v-else class="menu-empty">尚未关联可用菜单</span>
    </div>

    <footer>
      <div>
        <span>排序 {{ module.order }}</span
        ><i /> <span>{{ module.accent }}</span>
      </div>
      <div>
        <ElButton
          v-hasPerm="['module_system:module:edit']"
          link
          type="primary"
          @click="$emit('edit')"
          >编辑</ElButton
        >
        <ElButton
          v-hasPerm="['module_system:module:delete']"
          link
          type="danger"
          @click="$emit('delete')"
          >删除</ElButton
        >
      </div>
    </footer>
  </article>
</template>

<script setup lang="ts">
import type { TagProps } from "element-plus";
import type { WorkspaceModule, WorkspaceModuleStatus } from "@/api/module_system/module";

const props = defineProps<{ module: WorkspaceModule }>();
defineEmits<{ edit: []; delete: [] }>();

const statusMap: Record<WorkspaceModuleStatus, { label: string; type: TagProps["type"] }> = {
  active: { label: "可用", type: "success" },
  coming_soon: { label: "规划中", type: "warning" },
  disabled: { label: "已停用", type: "info" },
};
const statusMeta = computed(() => statusMap[props.module.status] ?? statusMap.disabled);
</script>

<style scoped>
.module-admin-card {
  --module-accent: #2563eb;

  position: relative;
  display: flex;
  flex-direction: column;
  min-height: 280px;
  padding: 21px;
  overflow: hidden;
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 15px;
  box-shadow: 0 7px 22px rgb(15 23 42 / 3%);
}

.accent-line {
  position: absolute;
  inset: 0 0 auto;
  height: 3px;
  background: var(--module-accent);
}

header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.module-icon {
  font-size: 25px;
  color: var(--module-accent);
}

.module-title {
  display: flex;
  gap: 10px;
  align-items: baseline;
  margin-top: 17px;
}

.module-title h2 {
  margin: 0;
  font-size: 18px;
  color: var(--el-text-color-primary);
}

.module-title code {
  font-size: 10px;
  color: var(--el-text-color-placeholder);
}

.module-description {
  min-height: 38px;
  margin: 8px 0 0;
  font-size: 12px;
  line-height: 1.6;
  color: var(--el-text-color-secondary);
}

.menu-summary {
  padding: 13px;
  margin-top: 17px;
  background: var(--el-fill-color-extra-light);
  border: 1px solid var(--el-border-color-extra-light);
  border-radius: 10px;
}

.menu-summary-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 11px;
  color: var(--el-text-color-secondary);
}

.menu-summary-head strong {
  color: var(--el-text-color-primary);
}

.menu-list {
  display: grid;
  gap: 7px;
  margin-top: 10px;
}

.menu-list span {
  display: flex;
  gap: 7px;
  align-items: center;
  overflow: hidden;
  text-overflow: ellipsis;
  font-size: 11px;
  color: var(--el-text-color-regular);
  white-space: nowrap;
}

.menu-list span > :first-child {
  flex: 0 0 auto;
  color: var(--module-accent);
}

.menu-empty {
  display: block;
  margin-top: 10px;
  font-size: 11px;
  color: var(--el-text-color-placeholder);
}

footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-top: 14px;
  margin-top: auto;
  font-size: 10px;
  color: var(--el-text-color-placeholder);
}

footer > div {
  display: flex;
  gap: 7px;
  align-items: center;
}

footer i {
  width: 2px;
  height: 2px;
  background: currentcolor;
  border-radius: 50%;
}

.accent-cyan {
  --module-accent: #0891b2;
}

.accent-violet {
  --module-accent: #7c3aed;
}

.accent-emerald {
  --module-accent: #059669;
}

.accent-amber {
  --module-accent: #d97706;
}

.accent-blue {
  --module-accent: #2563eb;
}

.accent-rose {
  --module-accent: #e11d48;
}

.accent-slate {
  --module-accent: #475569;
}

.accent-indigo {
  --module-accent: #4f46e5;
}

.accent-orange {
  --module-accent: #ea580c;
}
</style>
