<script setup lang="ts">
import FinanceSearchBar from "@/views/module_finance/components/FinanceSearchBar.vue";
import { reactive, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { resolveStatusColumns, renderTableOperationCell } from "@utils";
import API, { type Audit, type Refund, type RefundPreview } from "@/api/module_finance";
import FaTableHeader from "@/components/tables/fa-table-header/index.vue";
import AuditTrail from "../components/AuditTrail.vue";
import RefundLedger from "../components/RefundLedger.vue";
import RefundImpact from "../components/RefundImpact.vue";
import {
  dateTime,
  money,
  providerName,
  reasonPrompt,
  searchFields,
  states,
  statusText,
  useFinanceList,
} from "../shared";
const route = useRoute(),
  router = useRouter();
const ledgerTab = ref("requests");
const {
  currentApp,
  rows,
  total,
  summary,
  loading,
  failed,
  busy,
  query,
  pagination,
  showSearchBar,
  load,
  search,
  reset,
  changePage,
  changeSize,
} = useFinanceList(API.refunds, {
  status: String(route.query.status || ""),
  keyword: String(route.query.keyword || ""),
});
const searchItems = searchFields(
  ["review", "queued", "processing", "unknown", "succeeded", "failed", "rejected"],
  "退款单号 / 原订单号 / 用户"
);
const selected = ref<Refund | null>(null),
  drawer = ref(false),
  detailLoading = ref(false),
  detailFailed = ref(false),
  audits = ref<Audit[]>([]);
let detailGeneration = 0;
const syncOpen = ref(false);
const syncForm = reactive({ order_no: "", refund_no: "", reason: "" });
async function syncExternalRefund() {
  if (
    busy.value ||
    !syncForm.order_no.trim() ||
    !syncForm.refund_no.trim() ||
    syncForm.reason.trim().length < 2
  )
    return;
  const scope = currentApp.value?.id;
  busy.value = true;
  try {
    await API.syncRefund({
      order_no: syncForm.order_no.trim(),
      refund_no: syncForm.refund_no.trim(),
      reason: syncForm.reason.trim(),
    });
    if (scope === currentApp.value?.id) {
      syncOpen.value = false;
      await load();
    }
  } finally {
    busy.value = false;
  }
}
async function details(row: Refund) {
  const stamp = ++detailGeneration;
  selected.value = row;
  drawer.value = true;
  audits.value = [];
  detailLoading.value = true;
  detailFailed.value = false;
  try {
    const data = (await API.refund(row.id)).data.data;
    if (stamp === detailGeneration) {
      selected.value = { ...row, ...data.refund };
      audits.value = data.audits;
    }
  } catch {
    if (stamp === detailGeneration) detailFailed.value = true;
  } finally {
    if (stamp === detailGeneration) detailLoading.value = false;
  }
}
const reviewOpen = ref(false),
  reviewLoading = ref(false),
  reviewFailed = ref(false);
const reviewRow = ref<Refund | null>(null),
  reviewPreview = ref<RefundPreview | null>(null),
  reviewReason = ref("");
let reviewGeneration = 0;
async function loadReviewPreview() {
  const stamp = ++reviewGeneration;
  reviewPreview.value = null;
  reviewFailed.value = false;
  if (!reviewRow.value) return;
  reviewLoading.value = true;
  try {
    const result = (await API.refundReviewPreview(reviewRow.value.id)).data.data;
    if (stamp === reviewGeneration) reviewPreview.value = result;
  } catch {
    if (stamp === reviewGeneration) reviewFailed.value = true;
  } finally {
    if (stamp === reviewGeneration) reviewLoading.value = false;
  }
}
async function approveWithPreview() {
  if (
    busy.value ||
    !reviewRow.value ||
    !reviewPreview.value ||
    reviewReason.value.trim().length < 2
  )
    return;
  const scope = currentApp.value?.id;
  busy.value = true;
  try {
    await API.reviewRefund(
      reviewRow.value.id,
      true,
      reviewReason.value.trim(),
      reviewPreview.value.preview_token
    );
    if (scope === currentApp.value?.id) {
      reviewOpen.value = false;
      drawer.value = false;
      await load();
    }
  } catch {
    if (scope === currentApp.value?.id) await loadReviewPreview();
  } finally {
    busy.value = false;
  }
}
async function review(row: Refund, approved: boolean) {
  if (busy.value) return;
  if (approved) {
    reviewRow.value = row;
    reviewReason.value = "";
    reviewOpen.value = true;
    await loadReviewPreview();
    return;
  }
  const scope = currentApp.value?.id;
  const reason = await reasonPrompt(
    `${row.refund_no}，${money(row.amount_fen)}。${approved ? `审核通过后提交真实退款；${row.entitlement_action === "terminate" ? "退款成功后终止该订单剩余权益" : "保留订阅和积分权益"}。` : "拒绝后释放该申请占用的可退余额。"}`,
    approved ? "审核通过退款" : "拒绝退款"
  );
  if (!reason || scope !== currentApp.value?.id) return;
  busy.value = true;
  try {
    await API.reviewRefund(row.id, approved, reason);
    if (scope === currentApp.value?.id) {
      drawer.value = false;
      await load();
    }
  } finally {
    busy.value = false;
  }
}
async function verify(row: Refund) {
  if (busy.value) return;
  const scope = currentApp.value?.id;
  const reason = await reasonPrompt(`按原退款号 ${row.refund_no} 核验处理结果。`, "核验退款");
  if (!reason || scope !== currentApp.value?.id) return;
  busy.value = true;
  try {
    await API.queryRefund(row.id, reason);
    if (scope === currentApp.value?.id) await load();
  } finally {
    busy.value = false;
  }
}
async function retry(row: Refund) {
  if (busy.value) return;
  const scope = currentApp.value?.id;
  const reason = await reasonPrompt(
    `重新提交原退款号 ${row.refund_no}，金额 ${money(row.amount_fen)}，继续使用原单幂等标识。请先核对渠道记录并填写重提依据。`,
    "按原退款单重提"
  );
  if (!reason || scope !== currentApp.value?.id) return;
  busy.value = true;
  try {
    await API.retryRefund(row.id, reason);
    if (scope === currentApp.value?.id) await load();
  } finally {
    busy.value = false;
  }
}
const { columnChecks, columns } = useTableColumns<Refund>(
  resolveStatusColumns<Refund>(() => [
    { prop: "refund_no", label: "退款单号", minWidth: 250, showOverflowTooltip: true },
    { prop: "order_no", label: "原支付订单号", minWidth: 225, showOverflowTooltip: true },
    {
      prop: "display_name",
      label: "用户",
      minWidth: 150,
      formatter: (r) => `${r.display_name || r.username} (#${r.user_id})`,
      showOverflowTooltip: true,
    },
    { prop: "provider", label: "退款渠道", width: 105, formatter: (r) => providerName(r.provider) },
    {
      prop: "amount_fen",
      label: "申请退款",
      width: 140,
      align: "right",
      formatter: (r) => money(r.amount_fen),
    },
    { prop: "status", label: "状态", width: 115, status: states },
    {
      prop: "entitlement_action",
      label: "权益处理",
      width: 150,
      formatter: (r) => (r.entitlement_action === "retain" ? "保留权益" : "终止剩余权益"),
    },
    { prop: "reason", label: "申请依据", minWidth: 200, showOverflowTooltip: true },
    { prop: "requested_by", label: "申请人ID", width: 105 },
    { prop: "reviewed_by", label: "审核人ID", width: 105 },
    {
      prop: "created_time",
      label: "申请时间",
      minWidth: 175,
      formatter: (r) => dateTime(r.created_time),
    },
    {
      prop: "completed_at",
      label: "完成时间",
      minWidth: 175,
      formatter: (r) => dateTime(r.completed_at),
    },
    { prop: "failure_reason", label: "渠道处理信息", minWidth: 200, showOverflowTooltip: true },
    {
      prop: "operation",
      label: "操作",
      width: 160,
      fixed: "right",
      formatter: (r) =>
        renderTableOperationCell([
          {
            key: "detail",
            label: "详情",
            artType: "custom",
            icon: "ri:file-list-line",
            run: () => void details(r),
          },
          ...(r.status === "review"
            ? [true, false].map((approved) => ({
                key: String(approved),
                label: approved ? "通过" : "拒绝",
                artType: "custom" as const,
                icon: approved ? "ri:check-line" : "ri:close-line",
                perm: "workspace:finance:refund:review",
                run: () => void review(r, approved),
              }))
            : []),
          ...(r.status === "unknown"
            ? [
                {
                  key: "retry",
                  label: "按原单重提",
                  artType: "custom" as const,
                  icon: "ri:restart-line",
                  perm: "workspace:finance:refund:review",
                  run: () => void retry(r),
                },
              ]
            : []),
          ...(["unknown", "processing"].includes(r.status)
            ? [
                {
                  key: "query",
                  label: "核验",
                  artType: "custom" as const,
                  icon: "ri:search-line",
                  perm: "workspace:finance:refund:review",
                  run: () => void verify(r),
                },
              ]
            : []),
        ]),
    },
  ])
);
watch(
  () => currentApp.value?.id,
  () => {
    reviewGeneration++;
    reviewOpen.value = false;
    reviewPreview.value = null;
    detailGeneration++;
    drawer.value = false;
    selected.value = null;
    syncOpen.value = false;
  }
);
</script>
<template>
  <main class="fa-full-height">
    <ElTabs v-model="ledgerTab"
      ><ElTabPane name="requests" label="退款申请" /><ElTabPane name="ledger" label="已确认退款"
    /></ElTabs>
    <RefundLedger v-if="ledgerTab === 'ledger'" />
    <template v-else>
      <template v-if="currentApp"
        ><FinanceSearchBar
          v-show="showSearchBar"
          :model-value="query"
          :items="searchItems"
          :is-expand="false"
          @update:model-value="Object.assign(query, $event)"
          @search="search"
          @reset="reset" /><ElCard
          class="fa-table-card"
          :style="{ marginTop: showSearchBar ? '12px' : '0' }"
          ><FaTableHeader
            v-model:columns="columnChecks"
            v-model:showSearchBar="showSearchBar"
            :loading="loading"
            @refresh="load"
            ><template #left
              ><ElButton
                v-hasPerm="['workspace:finance:order:list']"
                type="primary"
                @click="router.push('/finance/orders')"
                ><FaSvgIcon icon="ri:refund-2-line" />选择订单申请退款</ElButton
              ><ElButton
                v-hasPerm="['workspace:finance:refund:review']"
                type="primary"
                plain
                @click="syncOpen = true"
                >核验商户退款</ElButton
              ><span class="summary"
                >{{ total }} 笔 · 申请金额 {{ money(summary.amount_fen || 0) }}</span
              ></template
            ></FaTableHeader
          ><ElAlert
            v-if="failed"
            title="退款列表加载失败，请重试"
            type="error"
            :closable="false" /><FaTable
            :loading="loading"
            :data="rows"
            :columns="columns"
            :pagination="pagination"
            @pagination:current-change="changePage"
            @pagination:size-change="changeSize" /></ElCard></template
      ><ElCard v-else class="fa-table-card"><ElEmpty description="请先选择客户端" /></ElCard>
      <ElDrawer v-model="drawer" title="退款详情" size="min(820px,96vw)" destroy-on-close
        ><ElSkeleton v-if="detailLoading" :rows="8" animated /><ElAlert
          v-if="detailFailed"
          title="退款详情加载失败"
          type="error"
          :closable="false" /><template v-if="selected && !detailLoading"
          ><ElDescriptions :column="2" border
            ><ElDescriptionsItem label="退款单号" :span="2">{{
              selected.refund_no
            }}</ElDescriptionsItem
            ><ElDescriptionsItem label="原订单" :span="2">{{
              selected.order_no
            }}</ElDescriptionsItem
            ><ElDescriptionsItem label="退款金额">{{
              money(selected.amount_fen)
            }}</ElDescriptionsItem
            ><ElDescriptionsItem label="状态">{{ statusText(selected.status) }}</ElDescriptionsItem
            ><ElDescriptionsItem label="权益处理">{{
              selected.entitlement_action === "retain" ? "保留权益" : "终止该订单剩余权益"
            }}</ElDescriptionsItem
            ><ElDescriptionsItem label="渠道">{{
              providerName(selected.provider)
            }}</ElDescriptionsItem
            ><ElDescriptionsItem label="申请人">#{{ selected.requested_by }}</ElDescriptionsItem
            ><ElDescriptionsItem label="审核人">{{
              selected.reviewed_by ? `#${selected.reviewed_by}` : "—"
            }}</ElDescriptionsItem
            ><ElDescriptionsItem label="退款依据" :span="2">{{
              selected.reason
            }}</ElDescriptionsItem
            ><ElDescriptionsItem label="审核依据" :span="2">{{
              selected.review_reason || "—"
            }}</ElDescriptionsItem
            ><ElDescriptionsItem label="审核时间">{{
              dateTime(selected.reviewed_at)
            }}</ElDescriptionsItem
            ><ElDescriptionsItem label="渠道提交时间">{{
              dateTime(selected.submitted_at)
            }}</ElDescriptionsItem
            ><ElDescriptionsItem label="完成时间">{{
              dateTime(selected.completed_at)
            }}</ElDescriptionsItem
            ><ElDescriptionsItem label="下次核验">{{
              dateTime(selected.next_attempt_at)
            }}</ElDescriptionsItem
            ><ElDescriptionsItem label="渠道退款流水" :span="2">{{
              selected.provider_refund_no || "—"
            }}</ElDescriptionsItem
            ><ElDescriptionsItem label="渠道返回信息" :span="2"
              >{{ selected.failure_code || "" }}
              {{ selected.failure_reason || "—" }}</ElDescriptionsItem
            ></ElDescriptions
          >
          <ElDescriptions
            v-if="selected.entitlement_result?.action === 'terminate'"
            class="detail-block"
            title="权益处理结果"
            :column="2"
            border
            ><ElDescriptionsItem
              v-if="selected.entitlement_result.subscription_after"
              label="处理后套餐"
              >{{ selected.entitlement_result.subscription_after }}</ElDescriptionsItem
            ><ElDescriptionsItem
              v-if="selected.entitlement_result.subscription_after"
              label="处理后到期时间"
              >{{
                dateTime(
                  typeof selected.entitlement_result.subscription_ends_at === "string"
                    ? selected.entitlement_result.subscription_ends_at
                    : null
                )
              }}</ElDescriptionsItem
            ><ElDescriptionsItem
              v-if="selected.entitlement_result.entitlement_kind !== 'duration'"
              label="回收可用积分"
              >{{ selected.entitlement_result.revoked_available }}</ElDescriptionsItem
            ><ElDescriptionsItem
              v-if="selected.entitlement_result.entitlement_kind !== 'duration'"
              label="取消待释放积分"
              >{{ selected.entitlement_result.cancelled_pending }}</ElDescriptionsItem
            ><ElDescriptionsItem
              v-if="selected.entitlement_result.entitlement_kind !== 'duration'"
              label="在途预留积分"
              >{{ selected.entitlement_result.reserved_at_refund }}</ElDescriptionsItem
            ><ElDescriptionsItem
              v-if="selected.entitlement_result.entitlement_kind !== 'duration'"
              label="已消费或过期"
              >{{ selected.entitlement_result.consumed_or_expired }}</ElDescriptionsItem
            ></ElDescriptions
          >
          <div class="detail-block"><AuditTrail :rows="audits" /></div></template
      ></ElDrawer>
      <ElDialog
        v-model="reviewOpen"
        title="确认退款及权益处理"
        width="min(640px,94vw)"
        :close-on-click-modal="!busy"
      >
        <ElDescriptions v-if="reviewRow" :column="1" border>
          <ElDescriptionsItem label="退款单号">{{ reviewRow.refund_no }}</ElDescriptionsItem>
          <ElDescriptionsItem label="退款金额">{{
            money(reviewRow.amount_fen)
          }}</ElDescriptionsItem>
          <ElDescriptionsItem label="权益处理">{{
            reviewRow.entitlement_action === "terminate" ? "终止该订单剩余权益" : "保留权益"
          }}</ElDescriptionsItem>
        </ElDescriptions>
        <ElSkeleton v-if="reviewLoading" :rows="5" animated />
        <ElAlert
          v-else-if="reviewFailed"
          title="权益预览加载失败，请重试"
          type="error"
          :closable="false"
        >
          <ElButton link type="primary" @click="loadReviewPreview">重新加载</ElButton>
        </ElAlert>
        <RefundImpact v-else-if="reviewPreview" :preview="reviewPreview" />
        <ElForm label-position="top">
          <ElFormItem label="审核依据" required
            ><ElInput v-model="reviewReason" type="textarea" maxlength="500" show-word-limit
          /></ElFormItem>
        </ElForm>
        <template #footer>
          <ElButton :disabled="busy" @click="reviewOpen = false">取消</ElButton>
          <ElButton
            type="primary"
            :loading="busy"
            :disabled="!reviewPreview || reviewLoading || reviewReason.trim().length < 2"
            @click="approveWithPreview"
            >确认通过并提交退款</ElButton
          >
        </template>
      </ElDialog>
      <ElDialog
        v-model="syncOpen"
        title="核验商户平台退款"
        width="min(560px,94vw)"
        :close-on-click-modal="false"
      >
        <ElAlert
          title="用于同步已在支付宝或微信商户平台发起的退款。只核验真实退款并同步款项、推广奖励，保留原订阅和积分权益，不会再次退款。"
          type="info"
          :closable="false"
        />
        <ElForm label-position="top" class="detail-block" @submit.prevent="syncExternalRefund">
          <ElFormItem label="原支付订单号" required
            ><ElInput v-model="syncForm.order_no" maxlength="128"
          /></ElFormItem>
          <ElFormItem label="商户退款单号 / 支付宝退款请求号" required
            ><ElInput v-model="syncForm.refund_no" maxlength="128"
          /></ElFormItem>
          <ElFormItem label="核验依据" required
            ><ElInput v-model="syncForm.reason" type="textarea" maxlength="500" show-word-limit
          /></ElFormItem>
        </ElForm>
        <template #footer
          ><ElButton :disabled="busy" @click="syncOpen = false">取消</ElButton
          ><ElButton
            type="primary"
            :loading="busy"
            :disabled="
              !syncForm.order_no.trim() ||
              !syncForm.refund_no.trim() ||
              syncForm.reason.trim().length < 2
            "
            @click="syncExternalRefund"
            >核验并同步</ElButton
          ></template
        >
      </ElDialog>
    </template>
  </main>
</template>
<style scoped>
.summary {
  margin-left: 12px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.detail-block {
  margin-top: 24px;
}
</style>
