/**
 * 快速入口配置
 * 包含：应用列表、快速链接等配置
 */
import type { FastEnterConfig } from "@/types/config";

const fastEnterConfig: FastEnterConfig = {
  // 显示条件（屏幕宽度）
  minWidth: 1200,
  // 应用列表
  applications: [
    {
      name: "用户管理",
      description: "系统用户管理与维护",
      icon: "ri:user-settings-line",
      iconColor: "#377dff",
      enabled: true,
      order: 1,
      routeName: "User",
    },
    {
      name: "角色管理",
      description: "角色权限配置与分配",
      icon: "ri:shield-user-line",
      iconColor: "#FF6B35",
      enabled: true,
      order: 2,
      routeName: "Role",
    },
    {
      name: "操作日志",
      description: "查看平台操作记录",
      icon: "ri:file-list-3-line",
      iconColor: "#13DEB9",
      enabled: true,
      order: 3,
      routeName: "Log",
    },
    {
      name: "个人中心",
      description: "维护当前账号资料",
      icon: "ri:user-3-line",
      iconColor: "#38C0FC",
      enabled: true,
      order: 4,
      routeName: "FastlinkProfile",
    },
  ],
  // 快速链接
  quickLinks: [
    {
      name: "登录",
      enabled: true,
      order: 1,
      routeName: "Login",
    },
    {
      name: "注册",
      enabled: true,
      order: 2,
      routeName: "Login",
    },
    {
      name: "忘记密码",
      enabled: true,
      order: 3,
      routeName: "Login",
    },
    {
      name: "操作日志",
      enabled: true,
      order: 4,
      routeName: "Log",
    },
    {
      name: "个人中心",
      enabled: true,
      order: 5,
      routeName: "FastlinkProfile",
    },
  ],
};

export default Object.freeze(fastEnterConfig);
