import { computed, onBeforeUnmount, reactive, ref, shallowRef, watch } from "vue";
import { storeToRefs } from "pinia";
import type { AxiosResponse } from "axios";
import { useClientAppStore } from "@/store/modules/client-app.store";
import type { AgreementQuery } from "@/api/module_agreement";

export function useAgreementList<T>(
  loader: (query: AgreementQuery) => Promise<AxiosResponse<ApiResponse<PageResult<T>>>>
) {
  const { currentApp } = storeToRefs(useClientAppStore());
  const rows = shallowRef<T[]>([]);
  const total = ref(0),
    page = ref(1),
    size = ref(20),
    loading = ref(false),
    failed = ref(false),
    showSearchBar = ref(true);
  const query = reactive({ keyword: "", status: "", has_draft: "" });
  const submitted = ref<Omit<AgreementQuery, "page_no" | "page_size">>({});
  let generation = 0;
  const pagination = computed(() => ({
    current: page.value,
    size: size.value,
    total: total.value,
  }));
  async function load() {
    const stamp = ++generation,
      app = currentApp.value?.id;
    if (!app) {
      rows.value = [];
      total.value = 0;
      loading.value = false;
      return;
    }
    loading.value = true;
    failed.value = false;
    try {
      const result = (
        await loader({ ...submitted.value, page_no: page.value, page_size: size.value })
      ).data.data;
      if (stamp !== generation || app !== currentApp.value?.id) return;
      rows.value = result.items;
      total.value = result.total;
    } catch {
      if (stamp === generation) {
        failed.value = true;
        rows.value = [];
        total.value = 0;
      }
    } finally {
      if (stamp === generation) loading.value = false;
    }
  }
  function search() {
    submitted.value = {
      keyword: query.keyword.trim(),
      status: query.status || undefined,
      has_draft: query.has_draft === "" ? undefined : query.has_draft === "true",
    };
    page.value = 1;
    void load();
  }
  function reset() {
    Object.assign(query, { keyword: "", status: "", has_draft: "" });
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
      reset();
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
    query,
    loading,
    failed,
    pagination,
    showSearchBar,
    load,
    search,
    reset,
    changePage,
    changeSize,
  };
}
