<template>
  <div
    class="hub-workspace-card group"
    :class="{
      'is-coming': module.status === 'coming_soon',
      'is-dark-mode': isDark
    }"
    :style="cardColorVars"
    @click="$emit('enter')"
  >
    <!-- 圆弧形波面展开颜色覆盖层（完全基于后台配置的颜色动态渲染） -->
    <div class="card-arc-sweep" aria-hidden="true" />

    <!-- 规划中状态标签（右上角） -->
    <span v-if="module.status === 'coming_soon'" class="status-pill">规划中</span>

    <!-- 卡片主体内容（1:1 参考图五 hub.html 居中沉稳通透布局） -->
    <div class="card-inner-flow">
      <!-- 居中拟物图腾徽标盒子（颜色完全由后台配置驱动） -->
      <div class="icon-glyph-box">
        <div class="glyph-bg" />
        <FaSvgIcon :icon="module.icon || 'ri:apps-line'" class="glyph-svg" />
      </div>

      <!-- 模块名称 -->
      <h3 class="module-title">{{ module.name }}</h3>

      <!-- 模块说明描述（对标 hub.html 换行排版） -->
      <p class="module-desc">{{ formattedDescription }}</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue";
import { useSettingsStore } from "@stores";
import { storeToRefs } from "pinia";
import type { WorkspaceModule } from "@/api/module_system/module";

const props = defineProps<{
  module: WorkspaceModule;
  index: number;
}>();

defineEmits<{
  enter: [];
}>();

const settingStore = useSettingsStore();
const { isDark } = storeToRefs(settingStore);

// 英文旧预设到 HEX 的平滑映射表
const PRESET_HEX_MAP: Record<string, string> = {
  cyan: "#06B6D4",
  violet: "#8B5CF6",
  emerald: "#10B981",
  amber: "#F59E0B",
  blue: "#00BFFF",
  rose: "#E63946",
  slate: "#64748B",
  indigo: "#6366F1",
  orange: "#F4A261",
  "purple-blue": "#8B5CF6",
  purple: "#A855F7",
  green: "#10B981",
  red: "#E63946",
};

// 动态解析 module.accent 颜色，并输出全套 CSS 变量驱动卡片样式与动效
const cardColorVars = computed(() => {
  const rawAccent = props.module.accent?.trim() || "#00BFFF";
  let hex = "#00BFFF";

  if (rawAccent.startsWith("#")) {
    hex = rawAccent;
  } else if (PRESET_HEX_MAP[rawAccent.toLowerCase()]) {
    hex = PRESET_HEX_MAP[rawAccent.toLowerCase()]!;
  }

  // 解析 R, G, B
  let r = 0;
  let g = 191;
  let b = 255;
  const cleanHex = hex.replace("#", "");

  if (cleanHex.length === 6) {
    r = parseInt(cleanHex.substring(0, 2), 16) || 0;
    g = parseInt(cleanHex.substring(2, 4), 16) || 191;
    b = parseInt(cleanHex.substring(4, 6), 16) || 255;
  } else if (cleanHex.length === 3) {
    r = parseInt(cleanHex[0]! + cleanHex[0]!, 16) || 0;
    g = parseInt(cleanHex[1]! + cleanHex[1]!, 16) || 191;
    b = parseInt(cleanHex[2]! + cleanHex[2]!, 16) || 255;
  }

  // 计算较深的过渡渐变终点色（用于 hover 圆弧覆盖层）
  const toR = Math.max(0, Math.round(r * 0.72));
  const toG = Math.max(0, Math.round(g * 0.72));
  const toB = Math.max(0, Math.round(b * 0.72));
  const itemTo = `rgb(${toR}, ${toG}, ${toB})`;

  // 计算深色模式下的沉稳专属底色（将主题色以微弱比例融入黑底，杜绝泛白）
  const bgR = Math.max(6, Math.round(r * 0.07));
  const bgG = Math.max(10, Math.round(g * 0.07));
  const bgB = Math.max(20, Math.round(b * 0.11));
  const darkBg = `rgb(${bgR}, ${bgG}, ${bgB})`;

  return {
    "--card-index": props.index,
    "--item-from": hex,
    "--item-to": itemTo,
    "--item-rgb": `${r}, ${g}, ${b}`,
    "--item-dark-bg": darkBg,
    "--item-dark-border": `rgba(${r}, ${g}, ${b}, 0.38)`,
    "--item-dark-glow": `rgba(${r}, ${g}, ${b}, 0.20)`,
  };
});

// 1:1 对齐 hub.html 真实业务文案
const FALLBACK_DESCRIPTIONS: Record<string, string> = {
  budget: "经营负责人+财务：建营收/成本模型→预算编制\nKPI树推导→确认下发",
  operations: "经营决策层：监控执行→异常预警→策略响应\n任务下发，保障目标达成",
  user_ops: "用户运营部：执行用户增长行动KPI\n获客/留存/激励转化",
  rule_engine: "运营自动化大脑：用户增长+客诉处理+经营风险\n三大引擎驱动闭环自运营",
  resource: "市场运营部：执行资源合作行动KPI\n商谈/上架/推广/分润",
  platform: "平台运营部：执行系统保障行动KPI\n研发/技术接入/运维/安全",
  finance: "财务团队：管理实际收入与支出流水\n对账/结算/报表，输出经营实际值",
  collaboration: "智能体监控/分析/建议/待办，人确认与执行\n高风险动作人工审批",
  analytics: "多维度经营数据分析\n趋势预测/对标复盘/决策支持",
};

const formattedDescription = computed(() => {
  return (
    props.module.description ||
    FALLBACK_DESCRIPTIONS[props.module.code] ||
    "进入全域智能体运营中枢"
  );
});
</script>

<style scoped>
.hub-workspace-card {
  --item-from: #00bfff;
  --item-to: #1d4ed8;
  --item-rgb: 0, 191, 255;
  --item-dark-bg: #0b1428;
  --item-dark-border: rgba(0, 191, 255, 0.35);
  --item-dark-glow: rgba(0, 191, 255, 0.16);

  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  box-sizing: border-box;
  width: 100%;
  height: 100%;
  padding: clamp(14px, 2vh, 22px) clamp(14px, 2vw, 22px);
  overflow: hidden;
  cursor: pointer;
  user-select: none;
  border-radius: 18px;

  /* 默认浅色模式：晶莹白玻璃 */
  background: rgba(255, 255, 255, 0.88);
  border: 1px solid rgba(var(--item-rgb), 0.22);
  box-shadow:
    0 1px 2px rgb(0 0 0 / 2%),
    0 8px 24px -4px rgba(var(--item-rgb), 0.08);

  transition:
    border-color 300ms ease,
    box-shadow 300ms ease,
    background-color 300ms ease;
  transform: none !important;
}

/* 浅色模式微渐变 */
:not(.is-dark-mode).hub-workspace-card {
  background-image: linear-gradient(
    135deg,
    rgba(255, 255, 255, 0.92) 0%,
    rgba(var(--item-rgb), 0.06) 100%
  );
  backdrop-filter: blur(10px);
}

/* 深色模式：沉稳深邃深蓝底（完全由配置颜色计算，彻底杜绝发白） */
.hub-workspace-card.is-dark-mode,
:global(html.dark) .hub-workspace-card {
  background-color: var(--item-dark-bg) !important;
  background-image: linear-gradient(
    135deg,
    rgba(var(--item-rgb), 0.14) 0%,
    rgba(0, 0, 0, 0.35) 100%
  ) !important;
  border: 1px solid var(--item-dark-border) !important;
  box-shadow:
    0 12px 32px rgba(0, 0, 0, 0.55),
    0 0 22px var(--item-dark-glow) !important;
  backdrop-filter: blur(8px);
}

/* 鼠标悬浮时边框高亮发光（颜色由配置颜色驱动） */
.hub-workspace-card:hover:not(.is-coming) {
  border-color: rgba(var(--item-rgb), 0.8) !important;
  box-shadow:
    0 14px 40px -4px rgba(var(--item-rgb), 0.42),
    0 0 32px var(--item-dark-glow) !important;
}

.hub-workspace-card.is-coming {
  cursor: not-allowed;
  opacity: 0.45;
}

/* 圆弧形波面展开颜色覆盖层（由配置颜色驱动，自左下角圆弧平滑扩散至右上角） */
.card-arc-sweep {
  position: absolute;
  bottom: 0;
  left: 0;
  z-index: 1;
  width: 320%;
  padding-bottom: 320%; /* 1:1 正圆形 */
  pointer-events: none;
  background: linear-gradient(135deg, var(--item-from), var(--item-to));
  border-radius: 50%;
  transform: translate(-50%, 50%) scale(0);
  transition: transform 520ms cubic-bezier(0.2, 0.85, 0.32, 1);
}

/* 鼠标悬停时自左下角以圆弧波面优雅覆盖，移出时反向收回 */
.hub-workspace-card:hover:not(.is-coming) .card-arc-sweep {
  transform: translate(-50%, 50%) scale(1);
}

/* 卡片内容流（居中对齐，通透饱满） */
.card-inner-flow {
  position: relative;
  z-index: 2;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  width: 100%;
  text-align: center;
}

/* 居中图标徽标盒子（色彩由配置颜色驱动） */
.icon-glyph-box {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 52px;
  height: 52px;
  margin-bottom: 11px;
}

.glyph-bg {
  position: absolute;
  inset: 0;
  border-radius: 15px;
  transition:
    transform 320ms cubic-bezier(0.34, 1.56, 0.64, 1),
    background 300ms ease,
    border-color 300ms ease;
  background: rgba(var(--item-rgb), 0.12);
  border: 1px solid rgba(var(--item-rgb), 0.3);
}

.hub-workspace-card.is-dark-mode .glyph-bg,
:global(html.dark) .glyph-bg {
  background: rgba(var(--item-rgb), 0.18);
  border: 1px solid rgba(var(--item-rgb), 0.45);
  box-shadow: 0 4px 14px -2px rgba(var(--item-rgb), 0.3);
}

.hub-workspace-card:hover:not(.is-coming) .glyph-bg {
  background: #fff !important;
  border-color: #fff !important;
  box-shadow: 0 8px 24px rgb(0 0 0 / 30%) !important;
  transform: scale(1.08);
}

.glyph-svg {
  position: relative;
  z-index: 3;
  font-size: 27px;
  color: var(--item-from);
  filter: drop-shadow(0 1px 2px rgb(0 0 0 / 18%));
  transition:
    color 300ms ease,
    transform 300ms ease;
}

.hub-workspace-card:hover:not(.is-coming) .glyph-svg {
  color: var(--item-to) !important;
  transform: scale(1.05);
}

/* 模块标题（纯白刀刻高光，绝不发虚） */
.module-title {
  margin: 0 0 6px;
  font-size: 16.5px;
  font-weight: 750;
  line-height: 1.25;
  color: var(--el-text-color-primary);
  letter-spacing: -0.015em;
  transition: color 300ms ease;
}

.hub-workspace-card.is-dark-mode .module-title,
:global(html.dark) .module-title {
  color: #fff;
  text-shadow: 0 1px 4px rgba(0, 0, 0, 0.6);
}

.hub-workspace-card:hover:not(.is-coming) .module-title {
  color: #fff !important;
  text-shadow: 0 1px 4px rgb(0 0 0 / 35%) !important;
}

/* 模块描述文案（深底高对比度，清晰可辨） */
.module-desc {
  display: -webkit-box;
  max-width: 92%;
  margin: 0;
  overflow: hidden;
  -webkit-line-clamp: 2;
  font-size: 12px;
  line-height: 1.5;
  color: var(--el-text-color-secondary);
  white-space: pre-line;
  -webkit-box-orient: vertical;
  transition: color 300ms ease;
}

.hub-workspace-card.is-dark-mode .module-desc,
:global(html.dark) .module-desc {
  color: rgba(255, 255, 255, 0.72);
}

.hub-workspace-card:hover:not(.is-coming) .module-desc {
  color: rgb(255 255 255 / 95%) !important;
}

/* 右上角规划中标签 */
.status-pill {
  position: absolute;
  top: 10px;
  right: 10px;
  z-index: 3;
  padding: 2px 8px;
  font-size: 10.5px;
  font-weight: 500;
  color: var(--el-text-color-secondary);
  background: rgba(var(--el-bg-color-rgb, 255, 255, 255), 0.75);
  backdrop-filter: blur(8px);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 999px;
  transition:
    background 300ms ease,
    color 300ms ease;
}

.hub-workspace-card.is-dark-mode .status-pill,
:global(html.dark) .status-pill {
  color: rgba(255, 255, 255, 0.65);
  background: rgba(255, 255, 255, 0.1);
  border-color: rgba(255, 255, 255, 0.16);
}

.hub-workspace-card:hover .status-pill {
  color: #fff;
  background: rgb(255 255 255 / 22%);
  border-color: rgb(255 255 255 / 35%);
}
</style>
