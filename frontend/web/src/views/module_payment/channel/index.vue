<template>
  <main class="payment-page fa-full-height">
    <ElAlert v-if="failed" title="支付渠道加载失败，请重试" type="error" :closable="false"><ElButton type="primary" link @click="loadChannels">重试</ElButton></ElAlert>
    <ElEmpty v-if="!currentApp" description="请先选择客户端" />
    <section class="summary-strip">
      <div>
        <span>渠道总数</span>
        <strong>{{ channels.length }}</strong>
        <small>固定支持渠道</small>
      </div>
      <div>
        <span>已启用</span>
        <strong>{{ enabledCount }}</strong>
        <small>当前收款通道</small>
      </div>
      <div>
        <span>参数就绪</span>
        <strong>{{ configuredCount }}</strong>
        <small>密钥与地址已识别</small>
      </div>
    </section>

    <section v-loading="loading" class="channel-grid">
      <ChannelCard
        v-for="channel in channels"
        :key="channel.provider"
        :channel="channel"
        :toggling="togglingProvider === channel.provider"
        :app-toggling="appTogglingProvider === channel.provider"
        :has-current-app="Boolean(currentApp)"
        @edit="openEditor(channel)"
        @toggle="toggleChannel(channel, $event)"
        @bind="bindChannel(channel, $event)"
        ><template #controls
          ><ChannelControls
            v-if="currentApp"
            :channel="channel"
            @changed="loadChannels" /></template
      ></ChannelCard>
    </section>

    <ChannelEditor
      v-model="editorVisible"
      :channel="editingChannel"
      :saving="saving"
      @save="saveChannel"
    />
  </main>
</template>

<script setup lang="ts">
import { ElMessage, ElMessageBox } from "element-plus";
import PaymentChannelAPI, {
  type PaymentChannel,
  type PaymentChannelForm,
} from "@/api/module_payment/channel";
import FinanceAPI, { type Channel } from "@/api/module_finance";
import ChannelControls from "@/views/module_finance/components/ChannelControls.vue";
import ChannelCard from "./components/channel-card.vue";
import ChannelEditor from "./components/channel-editor.vue";
import { useClientAppStore } from "@stores";

defineOptions({ name: "PaymentChannelManagement" });

const channels = ref<(PaymentChannel & Channel)[]>([]);
const { currentApp } = storeToRefs(useClientAppStore());
const loading = ref(false);
const failed = ref(false);
const saving = ref(false);
const editorVisible = ref(false);
const editingChannel = ref<PaymentChannel | null>(null);
const togglingProvider = ref<PaymentChannel["provider"] | null>(null);
const appTogglingProvider = ref<PaymentChannel["provider"] | null>(null);

const enabledCount = computed(() => channels.value.filter((item) => item.enabled && item.app_enabled && item.configured).length);
const configuredCount = computed(() => channels.value.filter((item) => item.configured).length);

let loadGeneration = 0;
async function loadChannels(): Promise<void> {
  const stamp = ++loadGeneration;
  if (!currentApp.value) {
    channels.value = [];
    loading.value = false;
    return;
  }
  loading.value = true;
  failed.value = false;
  try {
    const response = await FinanceAPI.channels();
    if (stamp === loadGeneration)
      channels.value = response.data.data as (PaymentChannel & Channel)[];
  } catch {
    if (stamp === loadGeneration) { failed.value = true; channels.value = []; }
  } finally {
    if (stamp === loadGeneration) loading.value = false;
  }
}

function replaceChannel(channel: PaymentChannel): void {
  const index = channels.value.findIndex((item) => item.provider === channel.provider);
  if (index >= 0) channels.value[index] = { ...channels.value[index]!, ...channel };
}

function openEditor(channel: PaymentChannel): void {
  editingChannel.value = channel;
  editorVisible.value = true;
}

async function saveChannel(form: PaymentChannelForm): Promise<void> {
  if (!editingChannel.value) return;
  saving.value = true;
  try {
    const response = await PaymentChannelAPI.update(editingChannel.value.provider, form);
    const channel = response.data.data;
    if (channel) {
      replaceChannel(channel);
      editingChannel.value = channel;
    }
    editorVisible.value = false;
  } finally {
    saving.value = false;
  }
}

async function toggleChannel(channel: PaymentChannel, enabled: boolean): Promise<void> {
  if (enabled) {
    await ElMessageBox.confirm(
      `确认启用${channel.name}吗？启用后业务系统可选择该渠道。请先确认支付产品已获批，并完成支付、回调、退款与对账联调。`,
      "启用支付渠道",
      { type: "warning", confirmButtonText: "确认启用" }
    );
  }
  togglingProvider.value = channel.provider;
  try {
    const response = await PaymentChannelAPI.toggle(channel.provider, enabled);
    if (response.data.data) replaceChannel(response.data.data);
    ElMessage.success(enabled ? `${channel.name}已启用` : `${channel.name}已停用`);
  } finally {
    togglingProvider.value = null;
  }
}

async function bindChannel(channel: PaymentChannel, enabled: boolean): Promise<void> {
  if (!currentApp.value) {
    ElMessage.warning("请先在顶栏选择客户端");
    return;
  }
  appTogglingProvider.value = channel.provider;
  try {
    const response = await PaymentChannelAPI.bind(channel.provider, enabled);
    if (response.data.data) replaceChannel(response.data.data);
    ElMessage.success(
      enabled
        ? `${currentApp.value.name}已可使用${channel.name}`
        : `${currentApp.value.name}已停用${channel.name}`
    );
  } finally {
    appTogglingProvider.value = null;
  }
}

watch(
  () => currentApp.value?.id,
  () => {
    editorVisible.value = false;
    channels.value = [];
    void loadChannels();
  },
  { immediate: true }
);
</script>

<style scoped>
.payment-page {
  box-sizing: border-box;
  padding: 24px;
  overflow: auto;
  background: var(--app-bg);
}

.summary-strip {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  margin-top: 0;
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 14px;
}

.summary-strip > div {
  display: grid;
  grid-template-columns: auto 1fr;
  column-gap: 12px;
  align-items: baseline;
  padding: 17px 20px;
}

.summary-strip > div + div {
  border-left: 1px solid var(--el-border-color-lighter);
}

.summary-strip span {
  grid-column: 1 / -1;
  margin-bottom: 5px;
  font-size: 11px;
  color: var(--el-text-color-secondary);
}

.summary-strip strong {
  font-size: 22px;
  color: var(--el-text-color-primary);
}

.summary-strip small {
  font-size: 11px;
  color: var(--el-text-color-placeholder);
}

.channel-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 18px;
  min-height: 320px;
  margin-top: 18px;
}

@media (width <= 900px) {
  .channel-grid {
    grid-template-columns: 1fr;
  }
}

@media (width <= 620px) {
  .payment-page {
    padding: 18px 14px;
  }

  .summary-strip {
    grid-template-columns: 1fr;
  }

  .summary-strip > div + div {
    border-top: 1px solid var(--el-border-color-lighter);
    border-left: 0;
  }
}
</style>
