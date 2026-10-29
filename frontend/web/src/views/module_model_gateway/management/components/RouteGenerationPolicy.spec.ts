import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import { defineComponent, ref } from "vue";
import ElementPlus from "element-plus";
import type { GenerationSettings } from "@/api/module_model_gateway";
import RouteGenerationPolicy from "./RouteGenerationPolicy.vue";

function policy(): GenerationSettings {
  return {
    policy_version: "qwen3.8-bounded-v1",
    enable_thinking: true,
    thinking_budget_tokens: 8000,
    total_timeout_seconds: 450,
    response_format: "text",
  };
}

function render(initial: GenerationSettings | null) {
  const state = ref(initial);
  const wrapper = mount(
    defineComponent({
      components: { RouteGenerationPolicy },
      setup: () => ({ state }),
      template: '<RouteGenerationPolicy v-model="state" :max-output-tokens="8192" />',
    }),
    { global: { plugins: [ElementPlus] } }
  );
  return { wrapper, state };
}

describe("route generation budget", () => {
  it("keeps an existing unmanaged route unchanged until explicitly enabled", async () => {
    const { wrapper, state } = render(null);
    expect(wrapper.text()).toContain("沿用供应商默认生成方式");
    expect(wrapper.find('input[aria-label="思考预算"]').exists()).toBe(false);
    expect(wrapper.findComponent(RouteGenerationPolicy).emitted()).toEqual({});
    await wrapper.find('[role="switch"]').trigger("click");
    expect(state.value).toEqual({
      ...policy(),
      thinking_budget_tokens: 4096,
      total_timeout_seconds: 600,
    });
    expect(wrapper.text()).toContain("8,192 Token");
    wrapper.unmount();
  });

  it("edits the requested field without mutating the original route", async () => {
    const original = Object.freeze(policy());
    const { wrapper, state } = render(original);
    const timeout = wrapper.find('input[aria-label="整次处理时限"]');
    await timeout.setValue("520");
    await timeout.trigger("change");
    expect(state.value).toEqual({ ...original, total_timeout_seconds: 520 });
    expect(original.total_timeout_seconds).toBe(450);
    wrapper.unmount();
  });

  it("turns thinking off with an explicit zero budget and disables its input", async () => {
    const { wrapper, state } = render(policy());
    await wrapper.find('[role="switch"][aria-label="启用思考"]').trigger("click");
    expect(state.value?.enable_thinking).toBe(false);
    expect(state.value?.thinking_budget_tokens).toBe(0);
    expect(wrapper.find('input[aria-label="思考预算"]').attributes("disabled")).toBeDefined();
    expect(state.value?.total_timeout_seconds).toBe(450);
    await wrapper.find('[role="switch"][aria-label="启用思考"]').trigger("click");
    expect(state.value?.thinking_budget_tokens).toBe(4096);
    wrapper.unmount();
  });

  it("disables an existing policy explicitly instead of leaving hidden active fields", async () => {
    const { wrapper, state } = render(policy());
    await wrapper.find('[role="switch"]').trigger("click");
    expect(state.value).toBeNull();
    expect(wrapper.find('input[aria-label="整次处理时限"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it("explains the prompt requirement when a stored route enforces JSON", () => {
    const { wrapper } = render({ ...policy(), response_format: "json_object" });
    expect(wrapper.text()).toContain("任务提示须明确要求 JSON");
    expect(wrapper.text()).toContain("暂不支持图片或文件直接输入");
    wrapper.unmount();
  });
});
