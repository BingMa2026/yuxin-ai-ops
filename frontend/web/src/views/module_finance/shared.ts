import { computed, onBeforeUnmount, reactive, ref, shallowRef, watch } from "vue";
import { storeToRefs } from "pinia";
import { useClientAppStore } from "@stores";
import { ElMessageBox } from "element-plus";
import { useRoute } from "vue-router";
import type { AxiosResponse } from "axios";
import type { SearchFormItem } from "@/components/forms/fa-search-bar/index.vue";
import type { StatusMap } from "@/utils/table/statusFormatter";
import type { FinancePage, FinanceQuery, Provider } from "@/api/module_finance";

export const money = (fen: number | null | undefined) =>
  fen == null
    ? "—"
    : new Intl.NumberFormat("zh-CN", { style: "currency", currency: "CNY" }).format(fen / 100);
export const dateTime = (value: string | null | undefined) =>
  value
    ? new Date(
        /[zZ]|[+-]\d\d:\d\d$/.test(value) ? value : `${value.replace(" ", "T")}Z`
      ).toLocaleString("zh-CN", { timeZone: "Asia/Shanghai", hour12: false })
    : "—";
export const providerName = (value: string | null) =>
  ({ alipay: "支付宝", wechat: "微信支付" })[value || ""] || "—";
export const states: StatusMap = {
  created: { type: "warning", text: "待支付" },
  unresolved: { type: "warning", text: "全部未结" },
  inflight: { type: "primary", text: "全部在途" },
  pending: { type: "warning", text: "待支付" },
  paid: { type: "success", text: "已支付" },
  closed: { type: "info", text: "已关闭" },
  failed: { type: "danger", text: "失败" },
  review: { type: "warning", text: "待审核" },
  queued: { type: "primary", text: "待处理" },
  processing: { type: "primary", text: "处理中" },
  unknown: { type: "danger", text: "结果未明" },
  succeeded: { type: "success", text: "已完成" },
  rejected: { type: "info", text: "已拒绝" },
  confirming: { type: "warning", text: "待确认收款" },
  completed: { type: "success", text: "核对完成" },
  downloading: { type: "primary", text: "下载核对中" },
  open: { type: "danger", text: "待处理" },
  resolved: { type: "success", text: "已处理" },
  refunded: { type: "info", text: "已全额退款" },
  partially_refunded: { type: "warning", text: "部分退款" },
  unfulfilled: { type: "danger", text: "权益未到账" },
};
export const refundStates: StatusMap = {
  none: { type: "info", text: "未退款" },
  partial: { type: "warning", text: "部分退款" },
  full: { type: "info", text: "全额退款" },
};
export const matchStates: StatusMap = {
  matched: { type: "success", text: "一致" },
  amount_mismatch: { type: "danger", text: "金额不一致" },
  trade_mismatch: { type: "danger", text: "渠道单号不一致" },
  refund_missing: { type: "warning", text: "系统缺少退款" },
  payment_missing: { type: "warning", text: "系统未确认支付" },
  channel_missing: { type: "danger", text: "渠道缺少流水" },
};
export const statusText = (state: string) => states[state]?.text || state;
export const actionText: Record<string, string> = {
  request: "提交申请",
  retry: "按原单重试",
  approve: "审核通过",
  reject: "审核拒绝",
  submit: "提交渠道",
  query: "渠道查单",
  query_requested: "申请查单",
  channel_result: "渠道核验结果",
  configure: "修改开关",
  external_refund_verified: "核验商户退款",
  repair_entitlements: "补发未到账权益",
  resolve: "处理差异",
  auto_resolve: "系统核验关闭",
  claim: "认领处理",
  reopen: "重新打开",
  reconcile: "完成对账",
  failed: "处理失败",
};
export const reasonPrompt = async (message: string, title: string) => {
  const result = await ElMessageBox.prompt(message, title, {
    inputType: "textarea",
    inputValidator: (v) =>
      (v?.trim().length >= 2 && v.trim().length <= 500) || "请填写2至500字的处理依据",
    confirmButtonText: "确认",
    cancelButtonText: "取消",
  }).catch(() => null);
  return result?.value.trim() || null;
};
export function useFinanceList<T>(
  loader: (q: FinanceQuery) => Promise<AxiosResponse<ApiResponse<FinancePage<T>>>>,
  initial: FinanceQuery = {}
) {
  const route = useRoute();
  const pagePath = route.path;
  initial = {
    ...initial,
    ...(route.query.keyword ? { keyword: String(route.query.keyword) } : {}),
    ...(route.query.status ? { status: String(route.query.status) } : {}),
  };
  const { currentApp } = storeToRefs(useClientAppStore());
  const rows = shallowRef<T[]>([]),
    total = ref(0),
    summary = ref<Record<string, number>>({});
  const loading = ref(false),
    failed = ref(false),
    busy = ref(false),
    showSearchBar = ref(true);
  const query = reactive({
    keyword: initial.keyword || "",
    provider: (initial.provider || "") as Provider | "",
    status: initial.status || "",
    dates:
      initial.start_date && initial.end_date
        ? [initial.start_date, initial.end_date]
        : ([] as string[]),
    min_amount_yuan: initial.min_amount_fen == null ? undefined : initial.min_amount_fen / 100,
    max_amount_yuan: initial.max_amount_fen == null ? undefined : initial.max_amount_fen / 100,
    time_field: initial.time_field || "created_time",
    purchase_type: initial.purchase_type || "",
    entitlement_kind: initial.entitlement_kind || "",
    mode_switch_status: initial.mode_switch_status || "",
  });
  const submitted = ref<FinanceQuery>({ ...initial }),
    page = ref(1),
    size = ref(20);
  const pagination = computed(() => ({
    current: page.value,
    size: size.value,
    total: total.value,
  }));
  let generation = 0;
  watch(
    () => route.fullPath,
    () => {
      if (route.path !== pagePath) return;
      query.keyword = String(route.query.keyword || "");
      query.status = String(route.query.status || "");
      query.provider =
        route.query.provider === "alipay" || route.query.provider === "wechat"
          ? route.query.provider
          : "";
      query.dates =
        route.query.start_date && route.query.end_date
          ? [String(route.query.start_date), String(route.query.end_date)]
          : [];
      query.time_field = route.query.time_field === "paid_at" ? "paid_at" : "created_time";
      query.min_amount_yuan = undefined;
      query.max_amount_yuan = undefined;
      query.purchase_type = "";
      search();
    }
  );
  const params = (): FinanceQuery => ({
    ...submitted.value,
    page_no: page.value,
    page_size: size.value,
  });
  async function load() {
    const stamp = ++generation;
    if (!currentApp.value) {
      rows.value = [];
      total.value = 0;
      loading.value = false;
      return;
    }
    loading.value = true;
    failed.value = false;
    try {
      const r = (await loader(params())).data.data;
      if (stamp !== generation) return;
      rows.value = r.items;
      total.value = r.total;
      summary.value = r.summary || {};
    } catch {
      if (stamp === generation) {
        failed.value = true;
        rows.value = [];
        total.value = 0;
        summary.value = {};
      }
    } finally {
      if (stamp === generation) loading.value = false;
    }
  }
  function search() {
    submitted.value = {
      keyword: (query.keyword || "").trim() || undefined,
      provider: query.provider || undefined,
      status: query.status || undefined,
      start_date: query.dates?.[0],
      end_date: query.dates?.[1],
      min_amount_fen:
        query.min_amount_yuan == null ? undefined : Math.round(query.min_amount_yuan * 100),
      max_amount_fen:
        query.max_amount_yuan == null ? undefined : Math.round(query.max_amount_yuan * 100),
      time_field: query.time_field,
      purchase_type: query.purchase_type || undefined,
      entitlement_kind:
        query.entitlement_kind === "credits" || query.entitlement_kind === "duration"
          ? query.entitlement_kind
          : undefined,
      mode_switch_status: query.mode_switch_status || undefined,
    };
    page.value = 1;
    void load();
  }
  function reset() {
    Object.assign(query, {
      keyword: "",
      provider: "",
      status: "",
      dates: [],
      min_amount_yuan: undefined,
      max_amount_yuan: undefined,
      purchase_type: "",
      entitlement_kind: "",
      mode_switch_status: "",
      time_field: "created_time",
    });
    search();
  }
  function changePage(value: number) {
    page.value = value;
    void load();
  }
  function changeSize(value: number) {
    size.value = value;
    page.value = 1;
    void load();
  }
  watch(
    () => currentApp.value?.id,
    () => {
      rows.value = [];
      summary.value = {};
      total.value = 0;
      page.value = 1;
      void load();
    },
    { immediate: true }
  );
  onBeforeUnmount(() => {
    generation++;
  });
  return {
    currentApp,
    rows,
    total,
    summary,
    loading,
    failed,
    busy,
    query,
    params,
    pagination,
    page,
    size,
    showSearchBar,
    load,
    search,
    reset,
    changePage,
    changeSize,
  };
}
export function searchFields(
  statuses: string[],
  keyword = "订单号 / 渠道单号 / 用户",
  amounts = true
): SearchFormItem[] {
  const fields: SearchFormItem[] = [
    {
      label: "搜索",
      key: "keyword",
      type: "input",
      props: { placeholder: keyword, clearable: true },
      span: 8,
    },
    {
      label: "支付渠道",
      key: "provider",
      type: "select",
      props: {
        clearable: true,
        options: [
          { label: "支付宝", value: "alipay" },
          { label: "微信支付", value: "wechat" },
        ],
      },
      span: 8,
    },
    {
      label: "状态",
      key: "status",
      type: "select",
      props: {
        clearable: true,
        options: statuses.map((value) => ({ label: states[value]?.text || value, value })),
      },
      span: 8,
    },
    {
      label: "日期范围",
      key: "dates",
      type: "daterange",
      props: {
        valueFormat: "YYYY-MM-DD",
        startPlaceholder: "开始日期",
        endPlaceholder: "结束日期",
        clearable: true,
      },
      span: 8,
    },
  ];
  if (amounts)
    fields.push(
      {
        label: "最低金额（元）",
        key: "min_amount_yuan",
        type: "number",
        props: { min: 0, precision: 2, controlsPosition: "right" },
        span: 8,
      },
      {
        label: "最高金额（元）",
        key: "max_amount_yuan",
        type: "number",
        props: { min: 0, precision: 2, controlsPosition: "right" },
        span: 8,
      }
    );
  return fields;
}
