<template>
  <main class="login-shell">
    <section class="login-panel" aria-labelledby="login-title">
      <div class="login-form-wrap">
        <div class="brand-mark" :aria-label="`${systemName} - 产品运营中心`">
          <FaLogo :size="38" />
          <span class="brand-title">产品运营中心</span>
        </div>

        <header class="login-heading">
          <h1 id="login-title">Welcome back</h1>
        </header>

        <div class="login-modes" role="tablist" aria-label="登录方式">
          <button type="button" class="login-mode is-active" role="tab" aria-selected="true">
            账号密码登录
          </button>
          <button type="button" class="login-mode" role="tab" aria-selected="false" disabled>
            手机验证码登录
          </button>
        </div>

        <ElForm
          ref="formRef"
          :model="loginForm"
          :rules="rules"
          class="login-form"
          @keyup.enter="submitLogin"
        >
          <ElFormItem prop="username">
            <ElInput
              v-model="loginForm.username"
              size="large"
              placeholder="请输入账号"
              aria-label="账号"
              autocomplete="username"
              clearable
            />
          </ElFormItem>

          <ElFormItem prop="password">
            <ElInput
              v-model="loginForm.password"
              size="large"
              type="password"
              placeholder="请输入密码"
              aria-label="密码"
              autocomplete="current-password"
              show-password
            />
          </ElFormItem>

          <ElButton
            class="login-submit"
            type="primary"
            size="large"
            :loading="loading"
            @click="submitLogin"
          >
            {{ loading ? "正在登录" : "登录" }}
          </ElButton>
        </ElForm>

        <footer v-if="copyright || record" class="login-footer">
          <span v-if="copyright">{{ copyright }}</span>
          <span v-if="copyright && record" aria-hidden="true">·</span>
          <span v-if="record">{{ record }}</span>
        </footer>
      </div>
    </section>

    <FaAgentAppWall class="login-visual" />
  </main>
</template>

<script setup lang="ts">
import type { FormInstance, FormRules } from "element-plus";
import { ElMessage } from "element-plus";
import type { LocationQuery, RouteLocationRaw } from "vue-router";
import { useRoute, useRouter } from "vue-router";
import type { LoginFormData } from "@/api/module_system/auth";
import AppConfig from "@/config";
import { useConfigStore, useUserStore } from "@stores";
import FaAgentAppWall from "./components/backdrops/FaAgentAppWall.vue";

defineOptions({ name: "Login" });

const REMEMBERED_USERNAME_KEY = "ops_login_remembered_username";
const router = useRouter();
const route = useRoute();
const configStore = useConfigStore();
const userStore = useUserStore();
const formRef = ref<FormInstance>();
const loading = ref(false);

const rememberedUsername = localStorage.getItem(REMEMBERED_USERNAME_KEY) || "";
const loginForm = reactive<LoginFormData>({
  username: rememberedUsername,
  password: "",
  remember: true,
  login_type: "PC端",
});

const rules: FormRules<LoginFormData> = {
  username: [{ required: true, message: "请输入账号", trigger: "blur" }],
  password: [
    { required: true, message: "请输入密码", trigger: "blur" },
    { min: 6, message: "密码长度不能少于 6 位", trigger: "blur" },
  ],
};

const systemName = computed(
  () => configStore.configData?.sys_name?.config_value || AppConfig.systemInfo.name
);
const DEFAULT_RECORD = "鄂ICP备2025138716号";
const copyright = computed(() => configStore.configData?.copyright?.config_value || "");
const record = computed(() => {
  const value = configStore.configData?.keep_record?.config_value;
  if (!value || value === "陕ICP备2025069493号-1") {
    return DEFAULT_RECORD;
  }
  return value;
});

function resolveRedirectTarget(query: LocationQuery): RouteLocationRaw {
  const rawRedirect = typeof query.redirect === "string" ? query.redirect : "/";
  try {
    const resolved = router.resolve(rawRedirect);
    return { path: resolved.path, query: resolved.query };
  } catch {
    return { path: "/" };
  }
}

onMounted(async () => {
  await configStore.getConfig(true);
  if (userStore.isLogin) await router.replace(resolveRedirectTarget(route.query));
});

async function submitLogin(): Promise<void> {
  if (loading.value) return;
  const valid = await formRef.value?.validate().catch(() => false);
  if (!valid) return;

  loading.value = true;
  try {
    await userStore.login({ ...loginForm });
    localStorage.setItem(REMEMBERED_USERNAME_KEY, loginForm.username);
    await router.replace(resolveRedirectTarget(route.query));
  } catch (error) {
    console.error("登录失败", error);
    ElMessage.error(
      error instanceof Error && error.message ? error.message : "登录失败，请检查账号和密码"
    );
  } finally {
    loading.value = false;
  }
}
</script>

<style scoped>
.login-shell {
  display: grid;
  grid-template-columns: 1fr 1fr;
  width: 100%;
  min-height: 100dvh;
  overflow: hidden;
  color: var(--el-text-color-primary);
  background: var(--el-bg-color);
}

.login-panel {
  position: relative;
  z-index: 2;
  display: grid;
  place-items: center;
  min-width: 0;
  background: var(--el-bg-color);
}

.login-form-wrap {
  width: min(424px, calc(100% - 48px));
  padding: 48px 0 34px;
  font-family: Inter, "SF Pro Display", "PingFang SC", "Microsoft YaHei", sans-serif;
  transform: translateY(-28px);
}

.brand-mark {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  margin-bottom: 34px;
  color: var(--el-text-color-primary);
}

.brand-title {
  font-size: 24px;
  font-weight: 600;
  line-height: 1;
  letter-spacing: 0.08em;
  color: var(--el-text-color-primary);
  white-space: nowrap;
  user-select: none;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}

.login-heading {
  text-align: center;
}

.login-heading h1 {
  margin: 0;
  font-size: 30px;
  font-weight: 660;
  line-height: 1.25;
  letter-spacing: -0.035em;
}

.login-modes {
  display: grid;
  grid-template-columns: 1fr 1fr;
  margin-top: 34px;
  border-bottom: 1px solid var(--el-border-color-lighter);
}

.login-mode {
  position: relative;
  height: 39px;
  padding: 0;
  font: inherit;
  font-size: 12px;
  font-weight: 500;
  color: var(--el-text-color-placeholder);
  background: transparent;
  border: 0;
}

.login-mode.is-active {
  color: var(--el-text-color-primary);
}

.login-mode.is-active::after {
  position: absolute;
  right: 0;
  bottom: -1px;
  left: 0;
  height: 2px;
  content: "";
  background: var(--el-text-color-primary);
}

.login-mode:disabled {
  cursor: not-allowed;
  opacity: 0.56;
}

.login-form {
  margin-top: 22px;
}

.login-form :deep(.el-form-item) {
  margin-bottom: 13px;
}

.login-form :deep(.el-form-item__content) {
  line-height: normal;
}

.login-form :deep(.el-input__wrapper) {
  min-height: 50px;
  padding: 0 15px;
  background: #f2f2f0;
  border-radius: 11px;
  box-shadow: 0 0 0 1px transparent inset;
  transition:
    background-color 160ms ease,
    box-shadow 160ms ease;
}

.login-form :deep(.el-input__wrapper:hover) {
  background: #ededeb;
}

.login-form :deep(.el-input__wrapper.is-focus) {
  background: var(--el-bg-color);
  box-shadow: 0 0 0 1px var(--el-text-color-primary) inset;
}

.login-form :deep(.el-input__inner) {
  height: 50px;
  font-size: 14px;
}

.login-form :deep(.el-input__inner::placeholder) {
  color: #8a8a86;
}

.login-form :deep(.el-input__inner:-webkit-autofill) {
  -webkit-text-fill-color: var(--el-text-color-primary);
  box-shadow: 0 0 0 1000px #f2f2f0 inset;
  transition: background-color 9999s ease-out 0s;
}

.login-submit {
  width: 100%;
  height: 50px;
  margin-top: 7px;
  font-size: 14px;
  font-weight: 650;
  color: #fff;
  background: #111;
  border-color: #111;
  border-radius: 999px;
  transition:
    background-color 160ms ease,
    border-color 160ms ease,
    transform 160ms ease;
}

.login-submit:hover,
.login-submit:focus-visible {
  background: #2b2b2b;
  border-color: #2b2b2b;
}

.login-submit:active {
  transform: translateY(1px);
}

.login-footer {
  display: flex;
  flex-wrap: wrap;
  gap: 3px 7px;
  justify-content: center;
  margin-top: 20px;
  font-size: 10px;
  line-height: 1.5;
  color: var(--el-text-color-placeholder);
  text-align: center;
}

html.dark .login-form :deep(.el-input__wrapper) {
  background: #1b1c1e;
}

html.dark .login-form :deep(.el-input__wrapper:hover) {
  background: #222326;
}

html.dark .login-form :deep(.el-input__wrapper.is-focus) {
  background: var(--el-bg-color);
  box-shadow: 0 0 0 1px rgb(255 255 255 / 72%) inset;
}

html.dark .login-form :deep(.el-input__inner::placeholder) {
  color: rgb(255 255 255 / 38%);
}

html.dark .login-form :deep(.el-input__inner:-webkit-autofill) {
  box-shadow: 0 0 0 1000px #1b1c1e inset;
}

html.dark .login-submit {
  color: #111;
  background: #f6f6f4;
  border-color: #f6f6f4;
}

html.dark .login-submit:hover,
html.dark .login-submit:focus-visible {
  background: #fff;
  border-color: #fff;
}

@media (width <= 900px) {
  .login-shell {
    grid-template-columns: 1fr;
  }

  .login-visual {
    display: none;
  }

  .login-panel {
    min-height: 100dvh;
  }
}

@media (width <= 520px) {
  .login-form-wrap {
    width: min(390px, calc(100% - 36px));
    padding: 36px 0 28px;
    transform: translateY(-16px);
  }

  .brand-mark {
    gap: 3px;
    margin-bottom: 30px;
  }

  .brand-title {
    font-size: 20px;
  }

  .login-heading h1 {
    font-size: 28px;
  }
}

@media (prefers-reduced-motion: reduce) {
  .login-form :deep(.el-input__wrapper),
  .login-submit {
    transition: none;
  }
}
</style>
