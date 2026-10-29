import { afterEach, beforeAll, expect, it, vi } from "vitest";
import { mount, flushPromises, type VueWrapper } from "@vue/test-utils";
import { reactive } from "vue";
import ElementPlus from "element-plus";
import type { PricingVersionForm } from "@/api/module_billing";
import PricingEditorDrawer from "./PricingEditorDrawer.vue";

let wrapper: VueWrapper;
beforeAll(() => {
  HTMLElement.prototype.scrollTo = vi.fn();
});
afterEach(() => {
  wrapper?.unmount();
  document.body.innerHTML = "";
});

it("updates totals from price and redistributes integer batches through the editor controls", async () => {
  const form = reactive<PricingVersionForm>({
    name: "首发价格体系",
    version: "MVP-1",
    credits_per_yuan: 1000,
    margin_baseline: 60,
    margin_floor: 25,
    subscription_cycle_days: 30,
    renewal_discount_rate: 0.9,
    account_priority: ["current_cycle"],
    templates: [
      {
        name: "基础版",
        code: "starter",
        plan_type: "subscription",
        tier_order: 10,
        tier_code: "starter",
        one_time_price_fen: 5900,
        recurring_price_fen: 5900,
        total_credits: 59000,
        billing_period_days: 30,
        credit_valid_days: 30,
        benefits: [],
        requires_active_subscription: false,
        order: 1,
        release_plan: [{ offset_day: 0, amount: 59000, account_type: "current_cycle" }],
      },
    ],
  });
  wrapper = mount(PricingEditorDrawer, {
    props: { visible: true, editing: true, saving: false, status: "published", form },
    attachTo: document.body,
    global: {
      plugins: [ElementPlus],
      stubs: { teleport: true, ElSelect: { template: "<div><slot /></div>" }, ElOption: true },
    },
  });
  await flushPromises();
  const clickButton = async (text: string) => {
    const button = wrapper.findAll("button").find((b) => b.text().includes(text));
    expect(button).toBeDefined();
    await button!.trigger("click");
    await flushPromises();
  };
  await clickButton("基础版");
  expect(form.templates[0]!.total_credits).toBe(59000);
  const priceInput = wrapper
    .findAll(".el-form-item")
    .find((f) => f.text().includes("首购价（元）"))!
    .find("input");
  await priceInput.setValue("99");
  await priceInput.trigger("change");
  await priceInput.trigger("blur");
  await flushPromises();
  expect(form.templates[0]!.one_time_price_fen).toBe(9900);
  expect(form.templates[0]!.total_credits).toBe(99000);
  await wrapper
    .findAll('[role="tab"]')
    .find((tab) => tab.text() === "积分释放")!
    .trigger("click");
  for (let i = 0; i < 3; i++) await clickButton("添加批次");
  expect(form.templates[0]!.release_plan.map((r) => r.amount)).toEqual([
    24750, 24750, 24750, 24750,
  ]);
  const totalInput = wrapper
    .findAll(".el-form-item")
    .find((f) => f.text().includes("总积分"))!
    .find("input");
  await totalInput.setValue("99");
  await totalInput.trigger("change");
  await totalInput.trigger("blur");
  await flushPromises();
  expect(form.templates[0]!.release_plan.map((r) => r.amount)).toEqual([25, 25, 25, 24]);
  await wrapper
    .findAll(".release-card button")
    .find((b) => b.text() === "移除")!
    .trigger("click");
  expect(form.templates[0]!.release_plan.map((r) => r.amount)).toEqual([33, 33, 33]);
});

it("edits custom duration and price without exposing or generating credits", async () => {
  const form = reactive<PricingVersionForm>({
    name: "时长价格体系",
    version: "duration-1",
    credits_per_yuan: 1000,
    margin_baseline: 60,
    margin_floor: 25,
    subscription_cycle_days: 30,
    renewal_discount_rate: 0.9,
    account_priority: ["current_cycle"],
    templates: [
      {
        entitlement_kind: "duration",
        name: "时长套餐",
        code: "duration_30",
        plan_type: "subscription",
        tier_order: 0,
        one_time_price_fen: 1000,
        recurring_price_fen: 900,
        total_credits: 0,
        billing_period_days: 30,
        credit_valid_days: 30,
        benefits: [],
        requires_active_subscription: false,
        order: 1,
        release_plan: [],
      },
    ],
  });
  wrapper = mount(PricingEditorDrawer, {
    props: { visible: true, editing: true, saving: false, status: "published", form },
    attachTo: document.body,
    global: {
      plugins: [ElementPlus],
      stubs: { teleport: true, ElSelect: { template: "<div><slot /></div>" }, ElOption: true },
    },
  });
  await flushPromises();
  await wrapper
    .findAll("button")
    .find((b) => b.text().includes("时长套餐"))!
    .trigger("click");
  await flushPromises();
  expect(wrapper.findAll('[role="tab"]').some((tab) => tab.text() === "积分释放")).toBe(false);
  const price = wrapper
    .findAll(".el-form-item")
    .find((f) => f.text().includes("首购价（元）"))!
    .find("input");
  await price.setValue("99");
  await price.trigger("change");
  await price.trigger("blur");
  await flushPromises();
  expect(form.templates[0]!.one_time_price_fen).toBe(9900);
  expect(form.templates[0]!.total_credits).toBe(0);
  expect(form.templates[0]!.release_plan).toEqual([]);
});
