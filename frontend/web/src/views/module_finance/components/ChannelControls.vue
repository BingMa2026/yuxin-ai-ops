<script setup lang="ts">
import { ref } from "vue";
import { storeToRefs } from "pinia";
import { useClientAppStore } from "@stores";
import API, { type Channel } from "@/api/module_finance";
import { dateTime, reasonPrompt } from "../shared";
const certificateLabels: Record<string, string> = {
  valid: "有效",
  expiring: "即将到期",
  expired: "已过期",
  unavailable: "未识别",
};
const props = defineProps<{ channel: Channel }>();
const emit = defineEmits<{ changed: [] }>();
const { currentApp } = storeToRefs(useClientAppStore());
const busy = ref(false);
const controls = [
  { key: "collection_enabled", label: "当前客户端收款" },
  { key: "refund_enabled", label: "当前客户端退款" },
  { key: "payout_enabled", label: "当前客户端提现" },
] as const;
function checked(key: string) {
  return key === "collection_enabled"
    ? props.channel.app_enabled
    : key === "refund_enabled"
      ? props.channel.refund_enabled
      : props.channel.payout_enabled;
}
function ready(key: string) {
  return key === "payout_enabled"
    ? props.channel.payout_ready
    : props.channel.configured && props.channel.enabled;
}
async function toggle(key: string, value: boolean) {
  if (busy.value) return;
  const scope = currentApp.value?.id;
  const reason = await reasonPrompt(
    `${currentApp.value?.name} / ${props.channel.name}：${value ? "开启" : "暂停"}${controls.find((c) => c.key === key)?.label}。已提交渠道的交易继续查单。`,
    "调整业务开关"
  );
  if (!reason || scope !== currentApp.value?.id) return;
  busy.value = true;
  try {
    await API.updateChannel(props.channel.provider, {
      collection_enabled: props.channel.app_enabled,
      refund_enabled: props.channel.refund_enabled,
      payout_enabled: props.channel.payout_enabled,
      [key]: value,
      reason,
    });
    if (scope === currentApp.value?.id) emit("changed");
  } finally {
    busy.value = false;
  }
}
</script>
<template>
  <section class="channel-controls">
    <div v-for="control in controls" :key="control.key" class="control-row">
      <span>{{ control.label }}</span
      ><ElTag
        :type="checked(control.key) && ready(control.key) ? 'success' : 'info'"
        size="small"
        >{{
          !checked(control.key) ? "已暂停" : ready(control.key) ? "已启用" : "配置未就绪"
        }}</ElTag
      ><ElSwitch
        v-hasPerm="['workspace:finance:channel:configure']"
        :model-value="checked(control.key)"
        :loading="busy"
        :disabled="!currentApp || (!checked(control.key) && !ready(control.key))"
        @change="toggle(control.key, Boolean($event))"
      />
    </div>
    <ElAlert
      v-if="!channel.payout_ready"
      :title="`提现：${channel.payout_reason}`"
      type="info"
      :closable="false"
    />
    <div v-for="certificate in channel.certificates" :key="certificate.name" class="certificate">
      <div>
        <span>{{ certificate.name }}</span
        ><small>{{
          certificate.expires_at ? `有效期至 ${dateTime(certificate.expires_at)}` : "未识别到证书"
        }}</small>
      </div>
      <ElTag
        :type="
          certificate.status === 'valid'
            ? 'success'
            : certificate.status === 'expiring'
              ? 'warning'
              : 'danger'
        "
        size="small"
        >{{ certificateLabels[certificate.status] }}</ElTag
      >
    </div>
    <small v-if="channel.last_changed_at" class="changed"
      >最近调整 {{ dateTime(channel.last_changed_at) }}</small
    >
  </section>
</template>
<style scoped>
.channel-controls {
  border-top: 1px solid var(--el-border-color-lighter);
  margin-top: 18px;
  padding-top: 8px;
}
.control-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 0;
}
.control-row > span {
  margin-right: auto;
  font-size: 13px;
}
.certificate {
  display: flex;
  gap: 12px;
  justify-content: space-between;
  align-items: center;
  margin: 16px 0;
}
.certificate span {
  font-size: 13px;
}
.certificate small {
  display: block;
  font-size: 11px;
  margin-top: 5px;
  color: var(--el-text-color-secondary);
}
.changed {
  font-size: 11px;
  color: var(--el-text-color-secondary);
}
</style>
