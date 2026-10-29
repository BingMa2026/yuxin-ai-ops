<template>
  <ElDialog
    :model-value="modelValue"
    :title="module ? '编辑工作台模块' : '新增工作台模块'"
    width="580px"
    destroy-on-close
    @update:model-value="$emit('update:modelValue', $event)"
  >
    <ElForm ref="formRef" :model="form" :rules="rules" label-position="top">
      <div class="form-grid">
        <ElFormItem label="模块名称" prop="name">
          <ElInput v-model="form.name" placeholder="例如：预算中心" maxlength="64" clearable />
        </ElFormItem>
        <ElFormItem label="模块编码" prop="code">
          <ElInput
            v-model="form.code"
            placeholder="例如：budget"
            maxlength="64"
            clearable
            :disabled="Boolean(module?.id)"
          />
        </ElFormItem>
      </div>

      <div class="form-grid">
        <ElFormItem label="模块图标" prop="icon">
          <!-- 采用与菜单管理完全一致的可视化图标选择器 -->
          <FaIconSelect v-model="form.icon" width="100%" />
        </ElFormItem>
        <ElFormItem label="排序序号" prop="order">
          <ElInputNumber
            v-model="form.order"
            :min="0"
            :max="9999"
            class="w-full!"
            controls-position="right"
          />
        </ElFormItem>
      </div>

      <!-- 主题色彩选择器与搭配推荐 -->
      <ElFormItem label="主题颜色" prop="accent">
        <div class="color-picker-row">
          <ElColorPicker
            v-model="form.accent"
            :predefine="PRESET_COLORS"
            color-format="hex"
            :show-alpha="false"
          />
          <ElInput
            v-model="form.accent"
            placeholder="#00BFFF"
            maxlength="20"
            style="width: 140px"
          />
          <div class="color-badge-preview" :style="{ backgroundColor: form.accent }">
            <span :style="{ color: isDarkColor(form.accent) ? '#ffffff' : '#111827' }">色彩预览</span>
          </div>
        </div>

        <!-- 搭配推荐快捷色块 -->
        <div class="preset-chips">
          <span class="preset-label">搭配推荐：</span>
          <button
            v-for="color in PALETTE_OPTIONS"
            :key="color.hex"
            type="button"
            class="palette-chip"
            :class="{ 'is-selected': form.accent.toLowerCase() === color.hex.toLowerCase() }"
            :style="{ '--chip-color': color.hex }"
            :title="`${color.name} (${color.hex})`"
            @click="form.accent = color.hex"
          >
            <span class="chip-swatch" />
            <span class="chip-name">{{ color.name }}</span>
          </button>
        </div>
      </ElFormItem>

      <ElFormItem label="状态" prop="status">
        <ElRadioGroup v-model="form.status">
          <ElRadioButton value="active">可用</ElRadioButton>
          <ElRadioButton value="coming_soon">规划中</ElRadioButton>
          <ElRadioButton value="disabled">停用</ElRadioButton>
        </ElRadioGroup>
      </ElFormItem>

      <ElFormItem label="模块业务说明" prop="description">
        <ElInput
          v-model="form.description"
          type="textarea"
          :rows="3"
          maxlength="255"
          show-word-limit
          placeholder="说明该模块的业务职责、主要使用角色及目标，如：经营负责人+财务：建营收/成本模型→预算编制..."
        />
      </ElFormItem>
    </ElForm>

    <template #footer>
      <ElButton @click="$emit('update:modelValue', false)">取消</ElButton>
      <ElButton type="primary" :loading="submitting" @click="submit">保存</ElButton>
    </template>
  </ElDialog>
</template>

<script setup lang="ts">
import { reactive, ref, watch, nextTick } from "vue";
import type { FormInstance, FormRules } from "element-plus";
import type { WorkspaceModule, WorkspaceModuleForm } from "@/api/module_system/module";

const props = defineProps<{
  modelValue: boolean;
  module: WorkspaceModule | null;
  submitting: boolean;
  defaultOrder: number;
}>();

const emit = defineEmits<{
  save: [form: WorkspaceModuleForm];
  "update:modelValue": [value: boolean];
}>();

// 精选高级搭配调色板
const PALETTE_OPTIONS = [
  { name: "紫晶星云", hex: "#8B5CF6" },
  { name: "冰川蓝", hex: "#00BFFF" },
  { name: "极光翠绿", hex: "#10B981" },
  { name: "幻彩紫", hex: "#A855F7" },
  { name: "暖阳金橙", hex: "#F4A261" },
  { name: "海青极客", hex: "#06B6D4" },
  { name: "深绯红", hex: "#E63946" },
  { name: "协同靛蓝", hex: "#6366F1" },
  { name: "琥珀金", hex: "#F59E0B" },
  { name: "经典蓝", hex: "#2563EB" },
];

const PRESET_COLORS = PALETTE_OPTIONS.map((item) => item.hex);

function isDarkColor(colorHex: string): boolean {
  if (!colorHex || !colorHex.startsWith("#")) return true;
  const hex = colorHex.replace("#", "");
  if (hex.length !== 6 && hex.length !== 3) return true;
  const r = parseInt(hex.length === 3 ? hex[0]! + hex[0]! : hex.substring(0, 2), 16);
  const g = parseInt(hex.length === 3 ? hex[1]! + hex[1]! : hex.substring(2, 4), 16);
  const b = parseInt(hex.length === 3 ? hex[2]! + hex[2]! : hex.substring(4, 6), 16);
  const yiq = (r * 299 + g * 587 + b * 114) / 1000;
  return yiq < 128;
}

const createDefault = (): WorkspaceModuleForm => ({
  code: "",
  name: "",
  icon: "ri:apps-line",
  description: "",
  accent: "#00BFFF",
  order: props.defaultOrder || 1,
  status: "active",
});

const formRef = ref<FormInstance>();
const form = reactive<WorkspaceModuleForm>(createDefault());

const rules: FormRules<WorkspaceModuleForm> = {
  name: [{ required: true, message: "请输入模块名称", trigger: "blur" }],
  code: [
    { required: true, message: "请输入模块编码", trigger: "blur" },
    {
      pattern: /^[a-z][a-z0-9_]*$/,
      message: "仅支持小写字母、数字和下划线，且以字母开头",
      trigger: "blur",
    },
  ],
  accent: [{ required: true, message: "请选择或输入主题颜色", trigger: "change" }],
  status: [{ required: true, message: "请选择状态", trigger: "change" }],
};

watch(
  () => [props.modelValue, props.module] as const,
  ([visible, module]) => {
    if (!visible) return;
    if (module) {
      Object.assign(form, {
        code: module.code,
        name: module.name,
        icon: module.icon || "ri:apps-line",
        description: module.description || "",
        accent: module.accent || "#00BFFF",
        order: module.order,
        status: module.status,
      });
    } else {
      Object.assign(form, createDefault());
    }
    nextTick(() => formRef.value?.clearValidate());
  },
  { immediate: true }
);

async function submit(): Promise<void> {
  await formRef.value?.validate();
  emit("save", { ...form });
}
</script>

<style scoped>
.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

.color-picker-row {
  display: flex;
  gap: 12px;
  align-items: center;
  width: 100%;
}

.color-badge-preview {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  height: 32px;
  padding: 0 16px;
  font-size: 12px;
  font-weight: 600;
  border-radius: 8px;
  box-shadow: 0 2px 6px rgb(0 0 0 / 12%);
  transition: all 0.2s ease;
}

.preset-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  margin-top: 10px;
}

.preset-label {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.palette-chip {
  display: inline-flex;
  gap: 6px;
  align-items: center;
  height: 24px;
  padding: 0 8px;
  font-size: 11px;
  color: var(--el-text-color-regular);
  cursor: pointer;
  background: var(--el-fill-color-light);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  transition: all 0.2s ease;
}

.palette-chip:hover {
  border-color: var(--chip-color);
}

.palette-chip.is-selected {
  font-weight: 600;
  color: #fff;
  background: var(--chip-color);
  border-color: var(--chip-color);
}

.chip-swatch {
  width: 10px;
  height: 10px;
  background-color: var(--chip-color);
  border-radius: 2px;
}

.palette-chip.is-selected .chip-swatch {
  background-color: #fff;
}

@media (width <= 640px) {
  .form-grid {
    grid-template-columns: 1fr;
    gap: 0;
  }
}
</style>
