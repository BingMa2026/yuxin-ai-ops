<template>
  <section class="placeholder-page">
    <div class="placeholder-card">
      <div class="placeholder-mark">
        <FaSvgIcon :icon="icon" />
      </div>
      <p class="placeholder-kicker">MVP PLACEHOLDER</p>
      <h1>{{ pageTitle }}</h1>
      <p class="placeholder-copy">{{ description }}</p>
      <div class="placeholder-meta">
        <span><FaSvgIcon icon="ri:checkbox-circle-line" />菜单与角色授权已接入</span>
        <span><FaSvgIcon icon="ri:route-line" />模块路由已完成隔离</span>
      </div>
      <ElButton type="primary" plain @click="router.push('/home')">
        <FaSvgIcon icon="ri:apps-2-line" />
        返回工作台
      </ElButton>
    </div>
  </section>
</template>

<script setup lang="ts">
import { useRoute, useRouter } from "vue-router";

defineOptions({ name: "WorkspacePlaceholder" });

const route = useRoute();
const router = useRouter();

const pageTitle = computed(() => String(route.meta.title || "功能建设中"));
const description = computed(() => {
  if (route.name === "ModelManagement") {
    return "后续将在此统一承载模型厂家、API 凭证、模型版本、成本计量与上下架状态。";
  }
  return "当前已完成模块入口、菜单隔离和角色授权接入，具体业务能力将在后续迭代中建设。";
});
const icon = computed(() => String(route.meta.icon || "ri:tools-line"));
</script>

<style scoped>
.placeholder-page {
  display: grid;
  place-items: center;
  min-height: min(68vh, 680px);
  padding: 28px;
}

.placeholder-card {
  width: min(620px, 100%);
  padding: clamp(34px, 6vw, 58px);
  text-align: center;
  background:
    radial-gradient(circle at 50% 0%, color-mix(in srgb, var(--el-color-primary) 10%, transparent), transparent 46%),
    var(--el-bg-color);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 22px;
  box-shadow: 0 18px 48px rgb(15 23 42 / 6%);
}

.placeholder-mark {
  display: grid;
  place-items: center;
  width: 58px;
  height: 58px;
  margin: 0 auto 18px;
  font-size: 27px;
  color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
  border-radius: 17px;
}

.placeholder-kicker {
  margin: 0 0 8px;
  font-size: 10px;
  font-weight: 700;
  color: var(--el-color-primary);
  letter-spacing: 0.16em;
}

h1 {
  margin: 0;
  font-size: clamp(27px, 4vw, 38px);
  color: var(--el-text-color-primary);
}

.placeholder-copy {
  max-width: 480px;
  margin: 16px auto 0;
  line-height: 1.8;
  color: var(--el-text-color-secondary);
}

.placeholder-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 9px;
  justify-content: center;
  margin: 24px 0 28px;
}

.placeholder-meta span {
  display: inline-flex;
  gap: 6px;
  align-items: center;
  padding: 7px 10px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  background: var(--el-fill-color-light);
  border-radius: 999px;
}

:deep(.el-button span) {
  gap: 7px;
}
</style>
