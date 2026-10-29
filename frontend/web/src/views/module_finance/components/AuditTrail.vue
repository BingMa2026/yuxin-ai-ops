<script setup lang="ts">
import type { Audit } from "@/api/module_finance";
import { actionText, dateTime } from "../shared";
defineProps<{ rows: Audit[] }>();
</script>
<template>
  <ElEmpty v-if="!rows.length" description="暂无操作记录" :image-size="60" />
  <ElTimeline v-else
    ><ElTimelineItem v-for="item in rows" :key="item.id" :timestamp="dateTime(item.created_time)"
      ><strong>{{ actionText[item.action] || item.action }}</strong
      ><span class="audit-actor">{{
        item.operator_id ? `操作员 #${item.operator_id}` : "系统"
      }}</span>
      <p>{{ item.reason }}</p></ElTimelineItem
    ></ElTimeline
  >
</template>
<style scoped>
.audit-actor {
  margin-left: 12px;
  color: var(--el-text-color-secondary);
}
p {
  margin-top: 6px;
  overflow-wrap: anywhere;
}
</style>
