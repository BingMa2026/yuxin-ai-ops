<script setup lang="ts">
import FinanceSearchBar from "@/views/module_finance/components/FinanceSearchBar.vue";
import { ref } from "vue";
import { renderTableOperationCell, resolveStatusColumns } from "@utils";
import API, { type RefundLedger } from "@/api/module_finance";
import FaTableHeader from "@/components/tables/fa-table-header/index.vue";
import OrderDrawer from "./OrderDrawer.vue";
import { dateTime, money, providerName, searchFields, states, useFinanceList } from "../shared";
const {
  currentApp,
  rows,
  total,
  summary,
  loading,
  failed,
  query,
  pagination,
  showSearchBar,
  load,
  search,
  reset,
  changePage,
  changeSize,
} = useFinanceList(API.refundLedger);
const searchItems = searchFields([], "退款流水 / 原订单号 / 用户").filter(
  (item) => item.key !== "status"
);
const orderId = ref<number | null>(null),
  drawer = ref(false);
const { columnChecks, columns } = useTableColumns<RefundLedger>(
  resolveStatusColumns<RefundLedger>(() => [
    { prop: "refund_no", label: "系统退款流水号", minWidth: 245, showOverflowTooltip: true },
    { prop: "order_no", label: "原支付订单号", minWidth: 225, showOverflowTooltip: true },
    {
      prop: "display_name",
      label: "用户",
      minWidth: 150,
      formatter: (r) => `${r.display_name || r.username} (#${r.user_id})`,
    },
    { prop: "provider", label: "退款渠道", width: 110, formatter: (r) => providerName(r.provider) },
    {
      prop: "amount_fen",
      label: "确认退款金额",
      width: 150,
      align: "right",
      formatter: (r) => money(r.amount_fen),
    },
    { prop: "status", label: "状态", width: 115, status: states },
    {
      prop: "refunded_at",
      label: "渠道退款完成时间",
      minWidth: 190,
      formatter: (r) => dateTime(r.refunded_at),
    },
    { prop: "reason", label: "退款依据", minWidth: 250, showOverflowTooltip: true },
    {
      prop: "operation",
      label: "操作",
      fixed: "right",
      width: 100,
      formatter: (r) =>
        renderTableOperationCell([
          {
            key: "order",
            label: "原订单",
            artType: "custom",
            icon: "ri:file-list-line",
            perm: "workspace:finance:order:list",
            run: () => {
              orderId.value = r.order_id;
              drawer.value = true;
            },
          },
        ]),
    },
  ])
);
</script>
<template>
  <section class="fa-full-height">
    <template v-if="currentApp">
      <FinanceSearchBar
        v-show="showSearchBar"
        :model-value="query"
        :items="searchItems"
        :is-expand="false"
        @update:model-value="Object.assign(query, $event)"
        @search="search"
        @reset="reset"
      />
      <ElCard class="fa-table-card" :style="{ marginTop: showSearchBar ? '12px' : '0' }">
        <FaTableHeader
          v-model:columns="columnChecks"
          v-model:showSearchBar="showSearchBar"
          :loading="loading"
          @refresh="load"
          ><template #left
            ><span>{{ total }} 笔 · 已确认退款 {{ money(summary.amount_fen || 0) }}</span></template
          ></FaTableHeader
        >
        <ElAlert v-if="failed" title="退款流水加载失败，请重试" type="error" :closable="false" />
        <FaTable
          :loading="loading"
          :data="rows"
          :columns="columns"
          :pagination="pagination"
          @pagination:current-change="changePage"
          @pagination:size-change="changeSize"
        />
      </ElCard>
    </template>
    <ElCard v-else><ElEmpty description="请先选择客户端" /></ElCard>
    <OrderDrawer v-model="drawer" :order-id="orderId" />
  </section>
</template>
