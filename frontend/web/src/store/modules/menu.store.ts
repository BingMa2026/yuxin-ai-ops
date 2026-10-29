/**
 * 菜单状态管理模块
 *
 * 提供菜单数据和动态路由的状态管理
 *
 * ## 主要功能
 *
 * - 菜单列表存储和管理
 * - 首页路径配置
 * - 动态路由注册和移除
 * - 路由移除函数管理
 * - 菜单宽度配置
 *
 * ## 使用场景
 *
 * - 动态菜单加载和渲染
 * - 路由权限控制
 * - 首页路径动态设置
 * - 登出时清理动态路由
 *
 * ## 工作流程
 *
 * 1. 获取菜单数据（前端/后端模式）
 * 2. 设置菜单列表和首页路径
 * 3. 注册动态路由并保存移除函数
 * 4. 登出时调用移除函数清理路由
 *
 * @module store/modules/menu.store
 * @author FastapiAdmin Team
 */
import { defineStore } from "pinia";
import { ref, computed } from "vue";
import type { AppRouteRecord } from "@/types/router";
import { getFirstMenuPath } from "@utils";
import { HOME_PAGE_PATH } from "@/router";
import { mergeShellRoutesIntoMenu } from "@/router/MenuProcessor";

/**
 * 菜单状态管理
 * 管理应用的菜单列表、首页路径、菜单宽度和动态路由移除函数
 */
export const useMenuStore = defineStore(
  "menuStore",
  () => {
    /** 首页路径 */
    const homePath = ref(HOME_PAGE_PATH);
    /** 菜单列表 */
    const menuList = ref<AppRouteRecord[]>([]);
    /** 当前业务模块，由路由元数据恢复，不持久化。 */
    const activeModuleId = ref<number | null>(null);
    /** 菜单宽度 */
    const menuWidth = ref("");
    /** 存储路由移除函数的数组 */
    const removeRouteFns = ref<(() => void)[]>([]);

    const moduleMenus = computed(() => {
      if (activeModuleId.value === null) return [];
      return menuList.value.filter(
        (menu) => Number(menu.meta?.workspaceModuleId) === activeModuleId.value
      );
    });

    /** 侧栏永远只展示当前模块下已授权的菜单。 */
    const visibleMenus = computed(() => moduleMenus.value);

    /**
     * 设置菜单列表
     * @param list 菜单路由记录数组
     */
    const setMenuList = (list: AppRouteRecord[]) => {
      const merged = mergeShellRoutesIntoMenu(list);
      menuList.value = merged;
      setHomePath(HOME_PAGE_PATH || getFirstMenuPath(merged));
    };

    const setActiveModuleId = (moduleId: number | null | undefined) => {
      activeModuleId.value = moduleId == null ? null : Number(moduleId);
    };

    const isNavigable = (route: AppRouteRecord): boolean =>
      Boolean(
        route.path &&
          !route.meta?.isHide &&
          !route.meta?.hidden &&
          !route.meta?.link &&
          route.meta?.isIframe !== true &&
          (route.component || route.meta?.shellRoute)
      );

    const findFirstNavigablePath = (routes: AppRouteRecord[]): string | undefined => {
      for (const route of routes) {
        if (route.redirect && typeof route.redirect === "string") return route.redirect;
        if (route.children?.length) {
          const nested = findFirstNavigablePath(route.children);
          if (nested) return nested;
        }
        if (isNavigable(route)) return route.path;
      }
      return undefined;
    };

    /** 获取模块排序最前的可访问页面。 */
    const getModuleEntryPath = (moduleId: number): string | undefined => {
      const roots = menuList.value.filter(
        (menu) => Number(menu.meta?.workspaceModuleId) === Number(moduleId)
      );
      return findFirstNavigablePath(roots);
    };

    /**
     * 获取首页路径
     * @returns 首页路径字符串
     */
    const getHomePath = () => homePath.value;

    /**
     * 设置主页路径
     * @param path 主页路径
     */
    const setHomePath = (path: string) => {
      homePath.value = path;
    };

    /**
     * 添加路由移除函数
     * @param fns 要添加的路由移除函数数组
     */
    const addRemoveRouteFns = (fns: (() => void)[]) => {
      removeRouteFns.value.push(...fns);
    };

    /**
     * 移除所有动态路由
     * 执行所有存储的路由移除函数并清空数组
     */
    const removeAllDynamicRoutes = () => {
      removeRouteFns.value.forEach((fn) => fn());
      removeRouteFns.value = [];
      activeModuleId.value = null;
    };

    /**
     * 清空路由移除函数数组
     */
    const clearRemoveRouteFns = () => {
      removeRouteFns.value = [];
    };

    return {
      menuList,
      activeModuleId,
      moduleMenus,
      visibleMenus,
      menuWidth,
      removeRouteFns,
      setMenuList,
      setActiveModuleId,
      getModuleEntryPath,
      getHomePath,
      setHomePath,
      addRemoveRouteFns,
      removeAllDynamicRoutes,
      clearRemoveRouteFns,
    };
  },
  {
    persist: {
      pick: ["homePath", "menuWidth"],
    },
  }
);
