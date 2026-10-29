<template>
  <section class="agent-wall" aria-label="多行业智能体应用展示">
    <div class="agent-wall__stage" :class="{ 'is-static': reduceMotion }">
      <div v-for="(track, trackIndex) in wallTracks" :key="trackIndex" class="agent-wall__track">
        <div v-if="reduceMotion" class="agent-wall__static-column">
          <figure
            v-for="(asset, assetIndex) in track.items"
            :key="`${trackIndex}-${assetIndex}-${asset}`"
            class="agent-wall__screen"
          >
            <img :src="asset" alt="" loading="eager" decoding="async" />
          </figure>
        </div>

        <Vue3Marquee
          v-else
          clone
          vertical
          :direction="track.direction"
          :duration="track.duration"
          :delay="track.delay"
          :pause-on-hover="false"
        >
          <figure
            v-for="(asset, assetIndex) in track.items"
            :key="`${trackIndex}-${assetIndex}-${asset}`"
            class="agent-wall__screen"
          >
            <img :src="asset" alt="" loading="eager" decoding="async" />
          </figure>
        </Vue3Marquee>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { usePreferredReducedMotion } from "@vueuse/core";
import { Vue3Marquee } from "vue3-marquee";

defineOptions({ name: "FaAgentAppWall" });

interface WallTrack {
  items: string[];
  direction: "normal" | "reverse";
  duration: number;
  delay: number;
}

const preferredMotion = usePreferredReducedMotion();
const reduceMotion = computed(() => preferredMotion.value === "reduce");

const assetModules = import.meta.glob("../../assets/wall-v5/*.webp", {
  eager: true,
  query: "?url",
  import: "default",
}) as Record<string, string>;

const wallAssets = Object.entries(assetModules)
  .sort(([a], [b]) => a.localeCompare(b))
  .map(([, url]) => url);

const trackSettings = [
  { direction: "normal" as const, duration: 960, delay: -240, start: 0, step: 3 },
  { direction: "reverse" as const, duration: 1120, delay: -392, start: 7, step: 5 },
  { direction: "normal" as const, duration: 840, delay: -378, start: 3, step: 7 },
  { direction: "reverse" as const, duration: 1280, delay: -704, start: 10, step: 9 },
  { direction: "normal" as const, duration: 1040, delay: -676, start: 5, step: 11 },
  { direction: "reverse" as const, duration: 1380, delay: -1035, start: 1, step: 13 },
  { direction: "normal" as const, duration: 1180, delay: -1003, start: 8, step: 15 },
];

const wallTracks = computed<WallTrack[]>(() => {
  if (!wallAssets.length) return [];

  return trackSettings.map(({ direction, duration, delay, start, step }) => ({
    direction,
    duration,
    delay,
    items: Array.from(
      { length: wallAssets.length },
      (_, index) => wallAssets[(start + index * step) % wallAssets.length]!
    ),
  }));
});
</script>

<style scoped>
.agent-wall {
  --agent-wall-surface: #f1f1ef;

  position: relative;
  width: 100%;
  min-width: 0;
  min-height: 100dvh;
  overflow: hidden;
  background: var(--agent-wall-surface);
}

.agent-wall__stage {
  position: absolute;
  top: 50%;
  left: 42%;
  display: flex;
  gap: 20px;
  width: 2220px;
  height: 3600px;
  transform: translate(-50%, -50%) rotate(45deg) scale(0.9);
  transform-origin: center;
}

.agent-wall__track {
  flex: 0 0 300px;
  width: 300px;
  min-width: 0;
  height: 3600px;
  overflow: hidden;
  background: transparent;
}

.agent-wall__track :deep(.vue3-marquee) {
  width: 300px;
  height: 3600px;
  overflow: visible;
  background: transparent !important;
}

.agent-wall__track :deep(.marquee) {
  gap: 20px;
  align-items: stretch;
  background: transparent !important;
}

.agent-wall__track :deep(.transparent-overlay) {
  background: transparent !important;
}

.agent-wall__screen {
  box-sizing: border-box;
  flex: 0 0 450px;
  width: 300px;
  height: 450px;
  padding: 0;
  margin: 0;
  overflow: hidden;
  background: #fff;
  border: 1px solid rgb(23 28 38 / 8%);
  border-radius: 22px;
  box-shadow: none;
}

.agent-wall__screen img {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.agent-wall__static-column {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

html.dark .agent-wall {
  --agent-wall-surface: #171819;
}

html.dark .agent-wall__screen {
  border-color: rgb(255 255 255 / 9%);
}

@media (width <= 1360px) {
  .agent-wall__stage {
    transform: translate(-50%, -50%) rotate(45deg) scale(0.82);
  }
}

@media (width <= 1080px) {
  .agent-wall__stage {
    transform: translate(-50%, -50%) rotate(45deg) scale(0.74);
  }
}

@media (prefers-reduced-motion: reduce) {
  .agent-wall__stage {
    transform: translate(-50%, -50%) rotate(45deg) scale(0.9);
  }
}
</style>
