import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it } from "vitest";
import type { AppRouteRecord } from "@/types/router";
import { useMenuStore } from "./menu.store";

const routes: AppRouteRecord[] = [
  {
    path: "/budget",
    redirect: "/budget/price-system",
    component: "LAYOUT",
    meta: { title: "预算中心", workspaceModuleId: 1 },
    children: [
      {
        path: "/budget/price-system",
        component: "/workspace/placeholder/index",
        meta: { title: "价格体系", workspaceModuleId: 1 },
      },
    ],
  },
  {
    path: "/platform",
    component: "LAYOUT",
    meta: { title: "平台管理", workspaceModuleId: 7 },
    children: [
      {
        path: "/platform/users",
        component: "/module_system/user/index",
        meta: { title: "用户管理", workspaceModuleId: 7 },
      },
    ],
  },
];

describe("menu store workspace isolation", () => {
  beforeEach(() => setActivePinia(createPinia()));

  it("only exposes roots in the active module", () => {
    const store = useMenuStore();
    store.setMenuList(routes);
    store.setActiveModuleId(7);

    expect(store.visibleMenus).toHaveLength(1);
    expect(store.visibleMenus[0]?.path).toBe("/platform");
  });

  it("uses the module redirect as its entry page", () => {
    const store = useMenuStore();
    store.setMenuList(routes);

    expect(store.getModuleEntryPath(1)).toBe("/budget/price-system");
    expect(store.getModuleEntryPath(99)).toBeUndefined();
  });

  it("clears module selection when dynamic routes are removed", () => {
    const store = useMenuStore();
    store.setActiveModuleId(1);
    store.removeAllDynamicRoutes();

    expect(store.activeModuleId).toBeNull();
  });
});
