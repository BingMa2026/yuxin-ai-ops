<template>
  <div class="client-app-switcher inline-flex shrink-0 items-center leading-none">
    <ElDropdown
      placement="bottom-end"
      trigger="click"
      :disabled="switching || apps.length === 0"
      popper-class="client-app-switcher__popover"
      @command="handleSwitch"
    >
      <button
        type="button"
        class="client-app-switcher__trigger"
        :aria-label="currentApp ? `当前客户端：${currentApp.name}` : '未选择客户端'"
      >
        <FaSvgIcon icon="ri:building-4-line" class="client-app-switcher__icon" />
        <strong v-if="currentApp" class="client-app-switcher__name" :title="currentApp.name">{{
          currentApp.name
        }}</strong>
        <span v-else class="client-app-switcher__placeholder">选择客户端</span>
        <FaSvgIcon
          :icon="switching ? 'ri:loader-4-line' : 'ri:arrow-down-s-line'"
          :class="{ 'client-app-switcher__loading': switching }"
        />
      </button>

      <template #dropdown>
        <div class="client-app-switcher__panel">
          <div class="client-app-switcher__heading">
            <span>切换客户端</span>
            <ElTag size="small" effect="plain">共 {{ apps.length }} 个</ElTag>
          </div>
          <ElDropdownMenu>
            <ElDropdownItem
              v-for="app in apps"
              :key="app.id"
              :command="app.id"
              :disabled="app.status !== 'active'"
              class="client-app-switcher__item"
            >
              <span class="client-app-switcher__mark">
                <FaSvgIcon icon="ri:building-line" />
              </span>
              <span class="client-app-switcher__meta">
                <strong :title="app.name">{{ app.name }}</strong>
                <small>{{ app.code }}</small>
              </span>
              <FaSvgIcon
                v-if="app.id === currentApp?.id"
                icon="ri:check-line"
                class="client-app-switcher__check"
              />
            </ElDropdownItem>
          </ElDropdownMenu>
        </div>
      </template>
    </ElDropdown>
  </div>
</template>

<script setup lang="ts">
import { ElMessageBox } from "element-plus";
import { useClientAppStore, useUserStore } from "@stores";

defineOptions({ name: "FaClientAppSwitcher" });

const clientAppStore = useClientAppStore();
const userStore = useUserStore();
const { apps, currentApp, switching, hasUnsavedChanges } = storeToRefs(clientAppStore);

async function handleSwitch(appId: number): Promise<void> {
  if (appId === currentApp.value?.id) return;
  if (hasUnsavedChanges.value) {
    await ElMessageBox.confirm(
      "当前页面有未保存内容，切换客户端后这些修改会丢失。是否继续？",
      "切换客户端",
      { confirmButtonText: "继续切换", cancelButtonText: "留在当前页", type: "warning" }
    );
  }
  await userStore.switchClientApp(appId);
}
</script>

<style scoped>
.client-app-switcher {
  display: inline-flex;
  flex-shrink: 0;
  align-items: center;
  line-height: 1;
}

.client-app-switcher :deep(.el-dropdown) {
  display: inline-flex;
  align-items: center;
  line-height: 1;
  vertical-align: middle;
}

.client-app-switcher :deep(.el-tooltip__trigger) {
  display: inline-flex;
  align-items: center;
  line-height: 1;
}

.client-app-switcher__trigger {
  display: inline-flex;
  gap: 7px;
  align-items: center;
  max-width: 210px;
  height: 32px;
  padding: 0 10px;
  line-height: 1;
  color: var(--el-text-color-regular);
  cursor: pointer;
  background: var(--el-fill-color-extra-light);
  border: 1px solid transparent;
  border-radius: 8px;
  transition: 160ms ease;
}

.client-app-switcher__trigger:hover {
  color: var(--el-color-primary);
  background: var(--el-fill-color-light);
  border-color: var(--el-border-color-light);
}

.client-app-switcher__trigger:focus-visible {
  outline: 2px solid var(--el-color-primary-light-3);
  outline-offset: 2px;
}

.client-app-switcher__icon,
.client-app-switcher__check {
  flex: 0 0 auto;
  color: var(--el-color-primary);
}

.client-app-switcher__name,
.client-app-switcher__placeholder,
.client-app-switcher__meta strong {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  font-size: 13px;
  font-weight: 500;
  white-space: nowrap;
}

.client-app-switcher__placeholder {
  color: var(--el-text-color-secondary);
}

.client-app-switcher__panel {
  width: min(300px, calc(100vw - 24px));
  padding: 8px;
}

@media screen and (width <= 640px) {
  .client-app-switcher__trigger {
    justify-content: center;
    width: 38px;
    padding: 0;
  }

  .client-app-switcher__name,
  .client-app-switcher__placeholder,
  .client-app-switcher__trigger > :last-child {
    display: none;
  }
}

.client-app-switcher__heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px 8px 10px;
  font-size: 13px;
  font-weight: 600;
  color: var(--el-text-color-primary);
  border-bottom: 1px solid var(--el-border-color-lighter);
}

.client-app-switcher__item {
  min-height: 56px;
  margin-top: 4px;
  border-radius: 8px;
}

.client-app-switcher__mark {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  color: var(--el-text-color-secondary);
  background: var(--el-fill-color-light);
  border-radius: 8px;
}

.client-app-switcher__meta {
  display: grid;
  min-width: 0;
  margin: 0 auto 0 10px;
}

.client-app-switcher__meta small,
.client-app-switcher__hint {
  font-size: 11px;
  color: var(--el-text-color-secondary);
}

.client-app-switcher__hint {
  padding: 10px 8px 2px;
  margin: 6px 0 0;
  line-height: 1.5;
  border-top: 1px solid var(--el-border-color-lighter);
}

.client-app-switcher__loading {
  animation: client-app-spin 1s linear infinite;
}

@keyframes client-app-spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
