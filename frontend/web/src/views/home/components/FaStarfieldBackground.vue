<template>
  <div class="starfield-scene" aria-hidden="true">
    <canvas ref="canvasRef" class="starfield-canvas" />
    <div class="glow-orb glow-1" />
    <div class="glow-orb glow-2" />
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount, watch } from "vue";
import { useSettingsStore } from "@stores";
import { storeToRefs } from "pinia";

defineOptions({ name: "FaStarfieldBackground" });

const canvasRef = ref<HTMLCanvasElement | null>(null);
const settingStore = useSettingsStore();
const { isDark } = storeToRefs(settingStore);

let ctx: CanvasRenderingContext2D | null = null;
let staticCanvas: HTMLCanvasElement | null = null;
let animationFrameId: number | null = null;

const TAU = Math.PI * 2;
let width = 0;
let height = 0;
let dpr = 1;

interface Meteor {
  x: number;
  y: number;
  vx: number;
  vy: number;
  length: number;
  life: number;
  maxLife: number;
}

let meteors: Meteor[] = [];
let nextMeteorAt = 0;
let previousTime = performance.now();

// 精致星系坐标
const constellations = [
  {
    name: "北斗七星",
    points: [
      [0.10, 0.25, 3.2], [0.17, 0.215, 3.6], [0.235, 0.25, 3.0],
      [0.275, 0.315, 3.4], [0.35, 0.29, 2.8], [0.415, 0.325, 3.5], [0.49, 0.295, 3.8]
    ]
  },
  {
    name: "仙后座",
    points: [
      [0.66, 0.19, 2.8], [0.725, 0.135, 3.3], [0.79, 0.205, 2.9],
      [0.855, 0.135, 3.5], [0.92, 0.19, 3.0]
    ]
  },
  {
    name: "猎户座",
    points: [
      [0.59, 0.54, 3.6], [0.705, 0.555, 3.0], [0.615, 0.64, 2.5],
      [0.65, 0.647, 2.8], [0.685, 0.64, 2.5], [0.60, 0.755, 3.0], [0.72, 0.76, 4.0]
    ]
  },
  {
    name: "天鹅座",
    points: [
      [0.29, 0.48, 3.5], [0.31, 0.57, 2.7], [0.33, 0.67, 3.8],
      [0.225, 0.59, 2.8], [0.405, 0.55, 3.1]
    ]
  }
];

function random(min: number, max: number): number {
  return min + Math.random() * (max - min);
}

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}

// 绘制锐利晶莹的四角飞镖星芒（不泛白糊）
function drawFourPointedStar(
  sctx: CanvasRenderingContext2D,
  cx: number,
  cy: number,
  outerR: number,
  innerRatio: number,
  fillColor: string,
  glowBlur = 0,
  glowColor = ""
) {
  const innerR = outerR * innerRatio;
  sctx.save();
  sctx.fillStyle = fillColor;

  if (glowBlur > 0 && glowColor) {
    sctx.shadowColor = glowColor;
    sctx.shadowBlur = glowBlur;
  }

  sctx.beginPath();
  for (let i = 0; i < 4; i++) {
    const outerA = (i * Math.PI) / 2 - Math.PI / 2;
    const innerA = outerA + Math.PI / 4;

    const ox = cx + Math.cos(outerA) * outerR;
    const oy = cy + Math.sin(outerA) * outerR;
    const ix = cx + Math.cos(innerA) * innerR;
    const iy = cy + Math.sin(innerA) * innerR;

    if (i === 0) {
      sctx.moveTo(ox, oy);
    } else {
      sctx.lineTo(ox, oy);
    }
    sctx.lineTo(ix, iy);
  }
  sctx.closePath();
  sctx.fill();

  // 中心微小锐利亮核
  sctx.fillStyle = "#ffffff";
  sctx.beginPath();
  sctx.arc(cx, cy, Math.max(0.6, innerR * 0.5), 0, TAU);
  sctx.fill();

  sctx.restore();
}

function buildStaticCanvas() {
  if (!width || !height) return;

  staticCanvas = document.createElement("canvas");
  staticCanvas.width = Math.round(width * dpr);
  staticCanvas.height = Math.round(height * dpr);
  const sctx = staticCanvas.getContext("2d");
  if (!sctx) return;

  sctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  const dark = isDark.value;

  // 1. 深邃纯净夜空底色（无过多泛白雾气）
  if (dark) {
    const bg = sctx.createLinearGradient(0, 0, width, height);
    bg.addColorStop(0, "#020716");
    bg.addColorStop(0.48, "#05132d");
    bg.addColorStop(0.78, "#030c1f");
    bg.addColorStop(1, "#010510");
    sctx.fillStyle = bg;
    sctx.fillRect(0, 0, width, height);

    // 微量纯净星云，透明度降为 0.08~0.10，避免大面积发白泛糊
    sctx.save();
    sctx.globalCompositeOperation = "screen";
    sctx.filter = `blur(${Math.max(45, width * 0.06)}px)`;
    const clouds: Array<[number, number, number, number, string]> = [
      [width * 0.72, height * 0.28, width * 0.22, height * 0.12, "rgba(14, 90, 190, 0.09)"],
      [width * 0.25, height * 0.72, width * 0.26, height * 0.10, "rgba(0, 130, 200, 0.07)"]
    ];
    for (const [x, y, rx, ry, color] of clouds) {
      sctx.fillStyle = color;
      sctx.beginPath();
      sctx.ellipse(x, y, rx, ry, -0.35, 0, TAU);
      sctx.fill();
    }
    sctx.restore();
  } else {
    // 浅色模式：极淡天青
    sctx.clearRect(0, 0, width, height);
    sctx.save();
    sctx.filter = `blur(${Math.max(50, width * 0.07)}px)`;
    const cloudsLight: Array<[number, number, number, number, string]> = [
      [width * 0.75, height * 0.28, width * 0.22, height * 0.10, "rgba(37, 99, 235, 0.04)"]
    ];
    for (const [x, y, rx, ry, color] of cloudsLight) {
      sctx.fillStyle = color;
      sctx.beginPath();
      sctx.ellipse(x, y, rx, ry, -0.35, 0, TAU);
      sctx.fill();
    }
    sctx.restore();
  }

  // 2. 绘制锐利晶莹星星（四角飞镖星芒为主，控制光晕不散）
  const starCount = clamp(Math.round((width * height) / 5800), 120, 260);
  sctx.save();

  for (let i = 0; i < starCount; i++) {
    const x = Math.random() * width;
    const y = Math.random() * height;
    const depth = Math.random();
    const isDartStar = Math.random() < 0.4;

    if (isDartStar) {
      const radius = 1.8 + depth ** 2.5 * 3.0; // 紧致星芒
      const alpha = random(0.3, 0.9);

      if (dark) {
        const fillColor = `rgba(215, 235, 255, ${alpha})`;
        drawFourPointedStar(sctx, x, y, radius, 0.26, fillColor, 0);
      } else {
        const fillColor = `rgba(29, 78, 216, ${alpha * 0.8})`;
        drawFourPointedStar(sctx, x, y, radius, 0.26, fillColor, 0);
      }
    } else {
      const radius = 0.35 + depth ** 3 * 1.2;
      const alpha = random(0.18, 0.75);
      sctx.fillStyle = dark
        ? `rgba(200, 225, 255, ${alpha})`
        : `rgba(30, 64, 175, ${alpha * 0.55})`;
      sctx.beginPath();
      sctx.arc(x, y, radius, 0, TAU);
      sctx.fill();
    }
  }
  sctx.restore();

  // 3. 星座核心星
  sctx.save();
  function drawConstellationStar(x: number, y: number, r: number) {
    if (!sctx) return;
    if (dark) {
      const fillColor = "rgba(240, 248, 255, 0.95)";
      const glowColor = "rgba(100, 170, 255, 0.5)";
      drawFourPointedStar(sctx, x, y, r * 1.2, 0.24, fillColor, 4, glowColor);
    } else {
      const fillColor = "rgba(29, 78, 216, 0.9)";
      drawFourPointedStar(sctx, x, y, r * 1.2, 0.24, fillColor, 0);
    }
  }

  for (const c of constellations) {
    c.points.forEach(([px, py, pr]) => {
      drawConstellationStar(px! * width, py! * height, pr!);
    });
  }
  drawConstellationStar(width * 0.085, height * 0.095, 4.2);
  sctx.restore();
}

function resize() {
  if (!canvasRef.value) return;
  dpr = Math.min(window.devicePixelRatio || 1, 1.5);
  width = window.innerWidth;
  height = window.innerHeight;

  canvasRef.value.width = Math.round(width * dpr);
  canvasRef.value.height = Math.round(height * dpr);

  ctx = canvasRef.value.getContext("2d");
  if (ctx) {
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  buildStaticCanvas();
}

function spawnMeteor(time: number) {
  meteors.push({
    x: random(width * 0.15, width * 0.95),
    y: random(-40, height * 0.35),
    vx: random(-640, -430),
    vy: random(330, 490),
    length: random(120, 210),
    life: 0,
    maxLife: random(0.75, 1.1)
  });
  nextMeteorAt = time + random(1400, 2800);
}

function drawMeteors(time: number, delta: number) {
  if (!ctx) return;
  if (time >= nextMeteorAt && meteors.length < 3) {
    spawnMeteor(time);
  }

  const dark = isDark.value;
  ctx.save();
  if (dark) ctx.globalCompositeOperation = "screen";
  ctx.lineCap = "round";

  meteors = meteors.filter((m) => {
    m.life += delta;
    m.x += m.vx * delta;
    m.y += m.vy * delta;

    const progress = m.life / m.maxLife;
    const speed = Math.hypot(m.vx, m.vy);
    const nx = m.vx / speed;
    const ny = m.vy / speed;
    const tailX = m.x - nx * m.length;
    const tailY = m.y - ny * m.length;
    const opacity = Math.sin(Math.min(1, progress) * Math.PI);

    if (!ctx) return false;
    const grad = ctx.createLinearGradient(tailX, tailY, m.x, m.y);

    if (dark) {
      grad.addColorStop(0, "rgba(105, 165, 255, 0)");
      grad.addColorStop(0.7, `rgba(137, 196, 255, ${opacity * 0.35})`);
      grad.addColorStop(1, `rgba(247, 252, 255, ${opacity * 0.92})`);
    } else {
      grad.addColorStop(0, "rgba(37, 99, 235, 0)");
      grad.addColorStop(0.7, `rgba(37, 99, 235, ${opacity * 0.4})`);
      grad.addColorStop(1, `rgba(29, 78, 216, ${opacity * 0.88})`);
    }

    ctx.strokeStyle = grad;
    ctx.lineWidth = 1.8;
    ctx.beginPath();
    ctx.moveTo(tailX, tailY);
    ctx.lineTo(m.x, m.y);
    ctx.stroke();

    return progress < 1;
  });

  ctx.restore();
}

function draw(time: number) {
  if (!ctx || !staticCanvas) return;
  const delta = Math.min((time - previousTime) / 1000, 0.05);
  previousTime = time;

  ctx.clearRect(0, 0, width, height);
  ctx.drawImage(staticCanvas, 0, 0, width, height);
  drawMeteors(time, delta);
}

function animate(time: number) {
  draw(time);
  animationFrameId = requestAnimationFrame(animate);
}

let resizeTimer: any = null;
function handleResize() {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(resize, 150);
}

watch(isDark, () => {
  buildStaticCanvas();
});

onMounted(() => {
  resize();
  nextMeteorAt = performance.now() + 500;
  animationFrameId = requestAnimationFrame(animate);
  window.addEventListener("resize", handleResize, { passive: true });
});

onBeforeUnmount(() => {
  if (animationFrameId !== null) {
    cancelAnimationFrame(animationFrameId);
  }
  clearTimeout(resizeTimer);
  window.removeEventListener("resize", handleResize);
});
</script>

<style scoped>
.starfield-scene {
  position: absolute;
  inset: 0;
  z-index: 0;
  width: 100%;
  height: 100%;
  overflow: hidden;
  pointer-events: none;
}

.starfield-canvas {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  display: block;
}

/* 降低环境大光球的透明度，避免产生大面积泛白光雾 */
.glow-orb {
  position: absolute;
  border-radius: 50%;
  filter: blur(140px);
  pointer-events: none;
  opacity: 0.35;
}

.glow-1 {
  width: 450px;
  height: 450px;
  background: rgba(37, 99, 235, 0.12);
  top: -160px;
  right: -100px;
}

.glow-2 {
  width: 350px;
  height: 350px;
  background: rgba(124, 58, 237, 0.08);
  bottom: -120px;
  left: -100px;
}
</style>
