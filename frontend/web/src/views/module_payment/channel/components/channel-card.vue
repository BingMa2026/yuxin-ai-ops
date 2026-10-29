<template>
  <article class="channel-card" :class="`provider-${channel.provider}`">
    <header class="channel-head">
      <span class="channel-mark">
        <FaSvgIcon :icon="meta.icon" />
      </span>
      <div class="channel-identity">
        <div class="channel-name-row">
          <h2>{{ channel.name }}</h2>
          <ElTag v-if="channel.enabled" type="success" effect="light" size="small">运行中</ElTag>
          <ElTag v-else type="info" effect="plain" size="small">未启用</ElTag>
        </div>
        <p>{{ meta.subtitle }}</p>
      </div>
      <ElSwitch
        v-hasPerm="['module_payment:channel:edit']"
        :model-value="channel.enabled"
        :loading="toggling"
        :disabled="!channel.configured && !channel.enabled"
        inline-prompt
        active-text="开"
        inactive-text="关"
        @change="$emit('toggle', Boolean($event))"
      />
    </header>

    <div class="channel-metrics">
      <div>
        <span>商户标识</span>
        <strong>{{ channel.merchant_identity || "尚未配置" }}</strong>
      </div>
      <div>
        <span>登记结算周期</span>
        <strong>{{ channel.settlement_cycle }}</strong>
      </div>
      <div>
        <span>登记费率</span>
        <strong>{{ Number(channel.fee_rate).toFixed(2) }}%</strong>
      </div>
    </div>

    <div class="readiness" :class="{ ready: channel.configured }">
      <span class="readiness-icon">
        <FaSvgIcon :icon="channel.configured ? 'ri:shield-check-line' : 'ri:error-warning-line'" />
      </span>
      <div>
        <strong>{{
          channel.configured ? "支付参数已识别" : `还缺 ${channel.missing_fields.length} 项环境配置`
        }}</strong>
        <p>
          {{
            channel.configured
              ? "密钥、验签材料与公网地址已识别，仍需完成支付链路验收"
              : "完成服务端环境变量后才可开启收款"
          }}
        </p>
      </div>
    </div>

    <div class="scene-row">
      <span>适用场景</span>
      <div>
        <ElTag v-for="scene in channel.scenes" :key="scene" effect="plain" size="small">{{
          scene
        }}</ElTag>
      </div>
    </div>

    <slot name="controls"
      ><div class="app-binding">
        <div>
          <span>当前客户端</span>
          <strong>{{ hasCurrentApp ? "收款能力授权" : "请先在顶栏选择客户端" }}</strong>
        </div>
        <ElSwitch
          v-hasPerm="['module_payment:channel:edit']"
          :model-value="channel.app_enabled"
          :loading="appToggling"
          :disabled="!hasCurrentApp || !channel.enabled || !channel.configured"
          inline-prompt
          active-text="可用"
          inactive-text="停用"
          @change="$emit('bind', Boolean($event))"
        />
      </div>
    </slot>
    <footer class="channel-actions">
      <span>{{ channel.mode === "production" ? "生产环境" : "沙箱环境" }}</span>
      <ElButton
        v-hasPerm="['module_payment:channel:edit']"
        link
        type="primary"
        @click="$emit('edit')"
      >
        管理渠道<FaSvgIcon icon="ri:arrow-right-line" />
      </ElButton>
    </footer>
  </article>
</template>

<script setup lang="ts">
import type { PaymentChannel } from "@/api/module_payment/channel";

const props = defineProps<{
  channel: PaymentChannel;
  toggling: boolean;
  appToggling: boolean;
  hasCurrentApp: boolean;
}>();

defineEmits<{
  edit: [];
  toggle: [enabled: boolean];
  bind: [enabled: boolean];
}>();

const providerMeta = {
  wechat: { icon: "ri:wechat-pay-line", subtitle: "微信支付商户平台 · Native 收款" },
  alipay: { icon: "ri:alipay-line", subtitle: "支付宝开放平台 · 当面付扫码收款" },
};
const meta = computed(() => providerMeta[props.channel.provider]);
</script>

<style scoped>
.channel-card {
  --provider-color: #1677ff;

  position: relative;
  padding: 24px;
  overflow: hidden;
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 16px;
  box-shadow: 0 8px 24px rgb(15 23 42 / 4%);
}

.channel-card::before {
  position: absolute;
  top: 0;
  right: 0;
  left: 0;
  height: 3px;
  content: "";
  background: var(--provider-color);
}

.provider-wechat {
  --provider-color: #07c160;
}

.provider-alipay {
  --provider-color: #1677ff;
}

.channel-head {
  display: flex;
  gap: 14px;
  align-items: center;
}

.channel-mark {
  display: grid;
  flex: 0 0 auto;
  place-items: center;
  width: 46px;
  height: 46px;
  font-size: 24px;
  color: var(--provider-color);
  background: color-mix(in srgb, var(--provider-color) 8%, var(--el-bg-color));
  border: 1px solid color-mix(in srgb, var(--provider-color) 20%, var(--el-border-color-lighter));
  border-radius: 13px;
}

.channel-identity {
  min-width: 0;
  margin-right: auto;
}

.channel-name-row {
  display: flex;
  gap: 9px;
  align-items: center;
}

.channel-name-row h2 {
  margin: 0;
  font-size: 17px;
  color: var(--el-text-color-primary);
}

.channel-identity p,
.readiness p {
  margin: 4px 0 0;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.channel-metrics {
  display: grid;
  grid-template-columns: 1.2fr 0.9fr 0.9fr;
  gap: 12px;
  padding: 19px 0;
  margin-top: 20px;
  border-top: 1px solid var(--el-border-color-extra-light);
  border-bottom: 1px solid var(--el-border-color-extra-light);
}

.channel-metrics span,
.scene-row > span {
  display: block;
  margin-bottom: 5px;
  font-size: 11px;
  color: var(--el-text-color-placeholder);
}

.channel-metrics strong {
  font-size: 13px;
  color: var(--el-text-color-primary);
}

.readiness {
  display: flex;
  gap: 11px;
  align-items: center;
  padding: 14px;
  margin-top: 18px;
  background: var(--el-color-warning-light-9);
  border: 1px solid var(--el-color-warning-light-7);
  border-radius: 11px;
}

.readiness.ready {
  background: var(--el-color-success-light-9);
  border-color: var(--el-color-success-light-7);
}

.readiness-icon {
  font-size: 20px;
  color: var(--el-color-warning);
}

.readiness.ready .readiness-icon {
  color: var(--el-color-success);
}

.readiness strong {
  font-size: 13px;
  color: var(--el-text-color-primary);
}

.scene-row {
  margin-top: 18px;
}

.app-binding {
  display: flex;
  gap: 12px;
  align-items: center;
  justify-content: space-between;
  padding: 13px 14px;
  margin-top: 18px;
  background: var(--el-fill-color-light);
  border-radius: 10px;
}

.app-binding div {
  display: grid;
  gap: 3px;
}

.app-binding span {
  font-size: 10px;
  color: var(--el-text-color-secondary);
}

.app-binding strong {
  font-size: 12px;
  color: var(--el-text-color-primary);
}

.scene-row > div {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
}

.channel-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 20px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.channel-actions :deep(.el-button span) {
  gap: 5px;
}

@media (width <= 620px) {
  .channel-card {
    padding: 19px;
  }

  .channel-metrics {
    grid-template-columns: 1fr 1fr;
  }

  .channel-metrics > div:first-child {
    grid-column: 1 / -1;
  }
}
</style>
