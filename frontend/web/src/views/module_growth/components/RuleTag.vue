<script setup lang="ts">
import { computed } from "vue";
const props = defineProps<{ value: string; label?: string; scheduled?: boolean }>();
const names: Record<string, string> = {
  draft: "待发布",
  published: "已发布",
  stopped: "已停用",
  ungraded: "未定级",
  auto: "自动发放",
  review: "待审核",
  simulation: "试运行",
  pending: "待到账",
  posted: "已到账",
  rejected: "已拒绝",
  reversed: "已冲正",
  started: "进行中",
  verified: "已核验",
  failed: "失败",
  cancelled: "已取消",
  simulated: "试运行",
  matched: "已匹配",
  skipped: "未匹配",
  enabled: "已开启",
  disabled: "未开启",
};
const tone = computed(() => {
  if (props.scheduled || ["draft", "review", "pending", "R3", "A3", "S"].includes(props.value))
    return "warning";
  if (
    ["published", "posted", "verified", "enabled", "auto", "R2", "A2", "matched"].includes(
      props.value
    )
  )
    return "success";
  if (["failed", "rejected", "reversed"].includes(props.value)) return "danger";
  if (["R1", "A1", "started"].includes(props.value)) return "primary";
  return "info";
});
</script>
<template>
  <ElTag :type="tone" effect="light" size="small" disable-transitions>{{
    scheduled ? "待生效" : label || names[value] || value
  }}</ElTag>
</template>
