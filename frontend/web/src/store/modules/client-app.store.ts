import { computed, ref } from "vue";
import { defineStore } from "pinia";
import type { ClientAppInfo } from "@/api/module_client/app";

export const useClientAppStore = defineStore("clientAppStore", () => {
  const apps = ref<ClientAppInfo[]>([]);
  const currentApp = ref<ClientAppInfo>();
  const switching = ref(false);
  const dirtySources = ref<string[]>([]);

  const hasCurrentApp = computed(() => Boolean(currentApp.value?.id));
  const hasUnsavedChanges = computed(() => dirtySources.value.length > 0);

  function setContext(nextApps: ClientAppInfo[], nextCurrent?: ClientAppInfo) {
    apps.value = nextApps;
    currentApp.value = nextCurrent;
  }

  function markDirty(source: string, dirty: boolean) {
    const values = new Set(dirtySources.value);
    if (dirty) values.add(source);
    else values.delete(source);
    dirtySources.value = [...values];
  }

  function clearDirty() {
    dirtySources.value = [];
  }

  function reset() {
    apps.value = [];
    currentApp.value = undefined;
    switching.value = false;
    clearDirty();
  }

  return {
    apps,
    currentApp,
    switching,
    hasCurrentApp,
    hasUnsavedChanges,
    setContext,
    markDirty,
    clearDirty,
    reset,
  };
});
