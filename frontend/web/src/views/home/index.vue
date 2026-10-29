<template>
  <div class="workspace-page">
    <!-- 对标 hub.html 的星空与流星背景（浅色深色自适应可见） -->
    <FaStarfieldBackground />

    <!-- 一屏自适应主容器 -->
    <main class="workspace-container">
      <!-- 顶部纯粹居中大标题（带流光微渐变） -->
      <header class="workspace-header">
        <h1 class="header-title">智能体运营 <span class="gradient-text">组织工作台</span></h1>
      </header>

      <!-- 扁平无边框统计行（非卡片形态） -->
      <section class="flat-stats-bar" aria-label="核心指标概览">
        <div v-for="metric in kpiMetrics" :key="metric.label" class="stat-item">
          <div class="stat-num-row">
            <span class="stat-num">{{ metric.value }}</span>
            <span class="stat-trend" :class="metric.trendType">
              <FaSvgIcon :icon="metric.trendIcon" class="trend-arrow" />
              {{ metric.trendValue }}
            </span>
          </div>
          <span class="stat-name">{{ metric.label }}</span>
        </div>
      </section>

      <!-- 业务模块 3x3 弹性网格（自适应充满空间，无多余空隙） -->
      <section v-if="loading" class="modules-grid" aria-label="模块加载中">
        <div v-for="index in 9" :key="index" class="skeleton-item">
          <ElSkeleton animated>
            <template #template>
              <div class="skeleton-center-flow">
                <ElSkeletonItem
                  variant="circle"
                  style="width: 52px; height: 52px; margin-bottom: 12px"
                />
                <ElSkeletonItem variant="h3" style="width: 42%; height: 18px; margin-bottom: 8px" />
                <ElSkeletonItem variant="text" style="width: 72%; height: 13px" />
              </div>
            </template>
          </ElSkeleton>
        </div>
      </section>

      <section v-else-if="modules.length" class="modules-grid" aria-label="业务模块列表">
        <WorkspaceCard
          v-for="(module, index) in modules"
          :key="module.id ?? module.code"
          :module="module"
          :index="index"
          @enter="enterModule(module)"
        />
      </section>

      <!-- 空状态 -->
      <section v-else class="empty-state">
        <FaSvgIcon icon="ri:shield-user-line" class="empty-icon" />
        <h2>暂无可用模块</h2>
        <p>当前账号尚未被分配任何业务模块权限</p>
      </section>

      <!-- 极简底栏说明 -->
      <footer class="workspace-footer">
        <span>{{ systemName }}</span>
        <span>•</span>
        <span>智能体矩阵管理架构</span>
      </footer>
    </main>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from "vue";
import { ElMessage, ElSkeleton, ElSkeletonItem } from "element-plus";
import { useRouter } from "vue-router";
import OperationsOverviewAPI, { type OperationsOverview } from "@/api/module_operations";
import WorkspaceModuleAPI, { type WorkspaceModule } from "@/api/module_system/module";
import AppConfig from "@/config";
import { useClientAppStore, useConfigStore, useMenuStore } from "@stores";
import WorkspaceCard from "./components/workspace-card.vue";
import FaStarfieldBackground from "./components/FaStarfieldBackground.vue";

defineOptions({ name: "Home" });

const router = useRouter();
const configStore = useConfigStore();
const menuStore = useMenuStore();
const { currentApp } = storeToRefs(useClientAppStore());

const loading = ref(true);
const modules = ref<WorkspaceModule[]>([]);
const overview = ref<OperationsOverview>();
const overviewLoaded = ref(false);

const systemName = computed(
  () => configStore.configData?.sys_name?.config_value || AppConfig.systemInfo.name
);

const rate = (value: number, previous: number) => {
  if (!previous) return value ? null : 0;
  return ((value - previous) / Math.abs(previous)) * 100;
};
const trend = (value: number, previous: number, point = false) => {
  const change = point ? value - previous : rate(value, previous);
  if (change === null)
    return { value: "上期无数据", type: "trend-neutral", icon: "ri:subtract-line" };
  if (Math.abs(change) < 0.05)
    return { value: "与上期持平", type: "trend-neutral", icon: "ri:subtract-line" };
  return {
    value: `${change > 0 ? "+" : ""}${change.toFixed(1)}${point ? " 个百分点" : "%"}`,
    type: change > 0 ? "trend-up" : "trend-down",
    icon: change > 0 ? "ri:arrow-right-up-line" : "ri:arrow-right-down-line",
  };
};
const metric = (label: string, value: string, current: number, previous: number, point = false) => {
  const change = trend(current, previous, point);
  return { label, value, trendValue: change.value, trendType: change.type, trendIcon: change.icon };
};
const kpiMetrics = computed(() => {
  const data = overview.value;
  if (!data) {
    return ["总用户", "近30日实收", "模型直接毛利率", "近30日活跃"].map((label) => ({
      label,
      value: "—",
      trendValue: currentApp.value
        ? overviewLoaded.value
          ? "数据暂不可用"
          : "数据加载中"
        : "请选择客户端",
      trendType: "trend-neutral",
      trendIcon: "ri:subtract-line",
    }));
  }
  return [
    metric(
      "总用户",
      data.summary.total_users.toLocaleString("zh-CN"),
      data.summary.total_users,
      data.previous.total_users
    ),
    metric(
      "近30日实收",
      `¥${data.summary.revenue_yuan.toLocaleString("zh-CN", { maximumFractionDigits: 2 })}`,
      data.summary.revenue_yuan,
      data.previous.revenue_yuan
    ),
    metric(
      "模型直接毛利率",
      `${data.summary.direct_margin_rate.toFixed(1)}%`,
      data.summary.direct_margin_rate,
      data.previous.direct_margin_rate,
      true
    ),
    metric(
      "近30日活跃",
      data.summary.active_users.toLocaleString("zh-CN"),
      data.summary.active_users,
      data.previous.active_users
    ),
  ];
});

async function loadModules(): Promise<void> {
  loading.value = true;
  try {
    const response = await WorkspaceModuleAPI.available();
    modules.value = response.data.data ?? [];
  } catch (error) {
    console.error("加载可用模块失败", error);
    modules.value = [];
    ElMessage.error("加载工作模块失败，请稍后重试");
  } finally {
    loading.value = false;
  }
}

async function loadOverview(): Promise<void> {
  overview.value = undefined;
  overviewLoaded.value = false;
  if (!currentApp.value) return;
  try {
    const response = await OperationsOverviewAPI.get(30);
    overview.value = response.data.data;
  } catch (error) {
    console.error("加载经营指标失败", error);
  } finally {
    overviewLoaded.value = true;
  }
}

async function enterModule(module: WorkspaceModule): Promise<void> {
  if (module.status !== "active" || module.id == null) return;
  const entryPath = menuStore.getModuleEntryPath(module.id);
  if (!entryPath) {
    ElMessage.warning("该模块暂无可访问菜单，请联系管理员授权");
    return;
  }
  menuStore.setActiveModuleId(module.id);
  await router.push(entryPath);
}

onMounted(loadModules);
watch(() => currentApp.value?.id, loadOverview, { immediate: true });
</script>

<style scoped>
.workspace-page {
  position: relative;
  box-sizing: border-box;
  height: calc(100vh - 60px);
  max-height: calc(100vh - 60px);
  overflow: hidden;
  background: #f8fafc;
}

:global(.dark) .workspace-page {
  background: #02091a;
}

.workspace-container {
  position: relative;
  z-index: 1;
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  width: min(1160px, 100%);
  height: 100%;
  padding: clamp(14px, 2vh, 22px) clamp(16px, 3vw, 36px);
  margin: 0 auto;
}

/* 顶部居中大标题 */
.workspace-header {
  flex: 0 0 auto;
  margin-bottom: clamp(10px, 1.4vh, 14px);
  text-align: center;
}

.header-title {
  margin: 0;
  font-size: clamp(26px, 3vw, 34px);
  font-weight: 800;
  line-height: 1.2;
  color: var(--el-text-color-primary);
  letter-spacing: -0.025em;
}

:global(.dark) .header-title {
  color: #fff;
}

.gradient-text {
  background: linear-gradient(135deg, #00bfff, #8b5cf6, #f4a261);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

/* 扁平无边框统计行（非卡片形态） */
.flat-stats-bar {
  display: flex;
  flex: 0 0 auto;
  gap: clamp(24px, 5vw, 64px);
  align-items: center;
  justify-content: center;
  padding: clamp(4px, 0.8vh, 10px) 0;
  margin-bottom: clamp(12px, 1.8vh, 18px);
}

.stat-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
}

.stat-num-row {
  display: flex;
  gap: 6px;
  align-items: baseline;
}

.stat-num {
  font-family:
    ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New",
    monospace;
  font-size: clamp(22px, 2.1vw, 28px);
  font-weight: 750;
  line-height: 1.15;
  color: var(--el-text-color-primary);
  letter-spacing: -0.02em;
}

:global(.dark) .stat-num {
  color: #fff;
}

.stat-trend {
  display: inline-flex;
  gap: 2px;
  align-items: center;
  font-size: 11px;
  font-weight: 600;
}

.stat-trend.trend-up {
  color: #059669;
}

.stat-trend.trend-down {
  color: var(--el-color-danger);
}

.stat-trend.trend-neutral {
  color: var(--el-text-color-placeholder);
}

.trend-arrow {
  font-size: 11px;
}

.stat-name {
  margin-top: 2px;
  font-size: 12px;
  font-weight: 500;
  color: var(--el-text-color-secondary);
  letter-spacing: 0.02em;
}

:global(.dark) .stat-name {
  color: rgb(255 255 255 / 55%);
}

/* 业务模块 3x3 弹性网格 */
.modules-grid {
  display: grid;
  flex: 1 1 auto;
  grid-template-rows: repeat(3, minmax(0, 1fr));
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: clamp(12px, 1.8vh, 20px);
  min-height: 0;
  margin-bottom: clamp(18px, 2.6vh, 32px);
}

.skeleton-item {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 22px 20px;
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 18px;
}

.skeleton-center-flow {
  display: flex;
  flex-direction: column;
  align-items: center;
  width: 100%;
}

.empty-state {
  display: flex;
  flex: 1;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: var(--el-text-color-secondary);
}

.empty-icon {
  margin-bottom: 12px;
  font-size: 36px;
  color: var(--el-color-primary);
}

.empty-state h2 {
  margin: 0 0 6px;
  font-size: 18px;
  color: var(--el-text-color-primary);
}

.empty-state p {
  margin: 0;
  font-size: 13px;
}

/* 底部微信息（与上方卡片保持呼吸感距离） */
.workspace-footer {
  display: flex;
  flex: 0 0 auto;
  gap: 8px;
  align-items: center;
  justify-content: center;
  padding-bottom: clamp(4px, 0.8vh, 10px);
  font-size: 11.5px;
  color: var(--el-text-color-placeholder);
}

@media (width <= 900px) {
  .workspace-page {
    height: auto;
    max-height: none;
    overflow-y: auto;
  }

  .modules-grid {
    grid-template-rows: none;
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .flat-stats-bar {
    flex-wrap: wrap;
    gap: 20px;
  }
}

@media (width <= 600px) {
  .modules-grid {
    grid-template-columns: 1fr;
  }
}
</style>
