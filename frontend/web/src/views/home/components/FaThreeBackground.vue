<template>
  <div ref="containerRef" class="three-wave-scene" aria-hidden="true" />
</template>

<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount, watch } from "vue";
import * as THREE from "three";
import { useSettingsStore } from "@stores";
import { storeToRefs } from "pinia";

defineOptions({ name: "FaThreeBackground" });

const containerRef = ref<HTMLDivElement | null>(null);
const settingStore = useSettingsStore();
const { isDark } = storeToRefs(settingStore);

let renderer: THREE.WebGLRenderer | null = null;
let scene: THREE.Scene | null = null;
let camera: THREE.PerspectiveCamera | null = null;
let particlesMesh: THREE.Points | null = null;
let animationFrameId: number | null = null;

// 3D 波浪网格参数
const AMOUNT_X = 55;
const AMOUNT_Y = 55;
const SEPARATION = 46;
const numParticles = AMOUNT_X * AMOUNT_Y;

// 鼠标位置平滑阻尼视差
let mouseX = 0;
let mouseY = 0;
let targetX = 0;
let targetY = 0;
let windowHalfX = window.innerWidth / 2;
let windowHalfY = window.innerHeight / 2;
let count = 0;

function createGlowParticleTexture(): THREE.Texture {
  const canvas = document.createElement("canvas");
  canvas.width = 64;
  canvas.height = 64;
  const ctx = canvas.getContext("2d");
  if (ctx) {
    const grad = ctx.createRadialGradient(32, 32, 0, 32, 32, 30);
    grad.addColorStop(0, "rgba(255, 255, 255, 1)");
    grad.addColorStop(0.3, "rgba(255, 255, 255, 0.9)");
    grad.addColorStop(0.65, "rgba(255, 255, 255, 0.35)");
    grad.addColorStop(1, "rgba(255, 255, 255, 0)");

    ctx.fillStyle = grad;
    ctx.beginPath();
    ctx.arc(32, 32, 28, 0, Math.PI * 2);
    ctx.fill();
  }
  const texture = new THREE.CanvasTexture(canvas);
  return texture;
}

function getThemeParams(dark: boolean) {
  if (dark) {
    return {
      colorA: new THREE.Color("#38bdf8"), // 天蓝辉光
      colorB: new THREE.Color("#818cf8"), // 靛紫辉光
      opacity: 0.72,
      size: 9,
      blending: THREE.AdditiveBlending,
    };
  }
  // 浅色模式强化显色度：采用高饱和科技深蓝与品蓝，保证在纯白背景下清晰立体
  return {
    colorA: new THREE.Color("#1d4ed8"), // 高对比皇家蓝
    colorB: new THREE.Color("#3b82f6"), // 鲜艳科技蓝
    opacity: 0.68,
    size: 8.5,
    blending: THREE.NormalBlending,
  };
}

function initThree() {
  if (!containerRef.value) return;

  const width = containerRef.value.clientWidth || window.innerWidth;
  const height = containerRef.value.clientHeight || window.innerHeight;

  // 1. 场景
  scene = new THREE.Scene();

  // 2. 摄像机（倾角俯瞰 3D 波浪曲面）
  camera = new THREE.PerspectiveCamera(65, width / height, 1, 10000);
  camera.position.set(0, 360, 1150);
  camera.lookAt(0, 0, 0);

  // 3. 几何网格
  const positions = new Float32Array(numParticles * 3);
  const colors = new Float32Array(numParticles * 3);

  const theme = getThemeParams(isDark.value);

  let i = 0;
  let p = 0;
  for (let ix = 0; ix < AMOUNT_X; ix++) {
    for (let iy = 0; iy < AMOUNT_Y; iy++) {
      positions[i] = ix * SEPARATION - (AMOUNT_X * SEPARATION) / 2;
      positions[i + 1] = 0;
      positions[i + 2] = iy * SEPARATION - (AMOUNT_Y * SEPARATION) / 2;

      const ratio = (ix + iy) / (AMOUNT_X + AMOUNT_Y);
      const mixed = theme.colorA.clone().lerp(theme.colorB, ratio);
      colors[p] = mixed.r;
      colors[p + 1] = mixed.g;
      colors[p + 2] = mixed.b;

      i += 3;
      p += 3;
    }
  }

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
  geometry.setAttribute("color", new THREE.BufferAttribute(colors, 3));

  // 4. 材质
  const material = new THREE.PointsMaterial({
    size: theme.size,
    vertexColors: true,
    map: createGlowParticleTexture(),
    transparent: true,
    opacity: theme.opacity,
    depthWrite: false,
    blending: theme.blending,
  });

  particlesMesh = new THREE.Points(geometry, material);
  scene.add(particlesMesh);

  // 5. 渲染器
  renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setSize(width, height);
  containerRef.value.appendChild(renderer.domElement);

  // 事件监听
  window.addEventListener("resize", handleResize);
  window.addEventListener("pointermove", handlePointerMove, { passive: true });
  document.addEventListener("visibilitychange", handleVisibilityChange);

  animate();
}

function handleResize() {
  if (!containerRef.value || !renderer || !camera) return;
  const width = containerRef.value.clientWidth || window.innerWidth;
  const height = containerRef.value.clientHeight || window.innerHeight;
  windowHalfX = width / 2;
  windowHalfY = height / 2;

  camera.aspect = width / height;
  camera.updateProjectionMatrix();
  renderer.setSize(width, height);
}

function handlePointerMove(e: PointerEvent) {
  mouseX = (e.clientX - windowHalfX) * 0.42;
  mouseY = (e.clientY - windowHalfY) * 0.32;
}

function handleVisibilityChange() {
  if (document.hidden) {
    if (animationFrameId !== null) {
      cancelAnimationFrame(animationFrameId);
      animationFrameId = null;
    }
  } else if (animationFrameId === null) {
    animate();
  }
}

function updateThemeParams() {
  if (!particlesMesh) return;
  const mat = particlesMesh.material as THREE.PointsMaterial;
  const geom = particlesMesh.geometry;
  const colorAttr = geom.attributes.color;
  if (!colorAttr) return;

  const theme = getThemeParams(isDark.value);
  mat.opacity = theme.opacity;
  mat.size = theme.size;
  mat.blending = theme.blending;
  mat.needsUpdate = true;

  const colors = colorAttr.array as Float32Array;
  let p = 0;
  for (let ix = 0; ix < AMOUNT_X; ix++) {
    for (let iy = 0; iy < AMOUNT_Y; iy++) {
      const ratio = (ix + iy) / (AMOUNT_X + AMOUNT_Y);
      const mixed = theme.colorA.clone().lerp(theme.colorB, ratio);
      colors[p] = mixed.r;
      colors[p + 1] = mixed.g;
      colors[p + 2] = mixed.b;
      p += 3;
    }
  }
  colorAttr.needsUpdate = true;
}

watch(isDark, updateThemeParams);

function animate() {
  animationFrameId = requestAnimationFrame(animate);

  if (!renderer || !scene || !camera || !particlesMesh) return;

  // 鼠标阻尼缓动
  targetX += (mouseX - targetX) * 0.045;
  targetY += (mouseY - targetY) * 0.045;

  camera.position.x = targetX;
  camera.position.y = 360 - targetY * 0.45;
  camera.lookAt(0, 0, 0);

  // 3D 曲面波浪起伏数学物理动画
  const posAttr = particlesMesh.geometry.attributes.position;
  if (!posAttr) return;
  const positions = posAttr.array as Float32Array;

  let i = 0;
  for (let ix = 0; ix < AMOUNT_X; ix++) {
    for (let iy = 0; iy < AMOUNT_Y; iy++) {
      positions[i + 1] =
        Math.sin((ix + count) * 0.28) * 26 + Math.sin((iy + count) * 0.46) * 26;
      i += 3;
    }
  }
  posAttr.needsUpdate = true;
  count += 0.048;

  renderer.render(scene, camera);
}

onMounted(() => {
  initThree();
});

onBeforeUnmount(() => {
  if (animationFrameId !== null) {
    cancelAnimationFrame(animationFrameId);
  }
  window.removeEventListener("resize", handleResize);
  window.removeEventListener("pointermove", handlePointerMove);
  document.removeEventListener("visibilitychange", handleVisibilityChange);

  if (particlesMesh) {
    particlesMesh.geometry.dispose();
    if (Array.isArray(particlesMesh.material)) {
      particlesMesh.material.forEach((m) => m.dispose());
    } else {
      particlesMesh.material.dispose();
    }
    scene?.remove(particlesMesh);
  }

  if (renderer) {
    renderer.dispose();
    renderer.forceContextLoss();
    if (renderer.domElement && renderer.domElement.parentNode) {
      renderer.domElement.parentNode.removeChild(renderer.domElement);
    }
  }

  scene = null;
  camera = null;
  renderer = null;
  particlesMesh = null;
});
</script>

<style scoped>
.three-wave-scene {
  position: absolute;
  inset: 0;
  z-index: 0;
  width: 100%;
  height: 100%;
  overflow: hidden;
  pointer-events: none;
}
</style>
