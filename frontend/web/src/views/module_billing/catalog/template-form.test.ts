import { expect, it } from "vitest";
import type { PricingTemplate } from "@/api/module_billing";
import { catalogTemplateFields } from "./template-form";

it("copies the complete trial template and fills legacy release accounts without mutating the source", () => {
  const source = {
    id: 1,
    code: "trial",
    name: "体验版",
    plan_type: "subscription",
    tier_code: "free",
    tier_order: 0,
    one_time_price_fen: 0,
    recurring_price_fen: 0,
    billing_period_days: 7,
    total_credits: 300,
    release_plan: [{ offset_day: 0, amount: 300 }],
    credit_valid_days: 7,
    benefits: ["完整功能体验"],
    requires_active_subscription: false,
    order: 1,
  } as PricingTemplate;
  const fields = catalogTemplateFields(source);
  expect(fields.tier_code).toBe("free");
  expect(fields.tier_order).toBe(0);
  expect(fields.benefit_period_days).toBe(7);
  expect(fields.release_plan).toEqual([
    { offset_day: 0, amount: 300, account_type: "current_cycle" },
  ]);
  expect(fields.benefits).toEqual(["完整功能体验"]);
  fields.release_plan![0]!.amount = 1000;
  fields.benefits!.push("新权益");
  expect(source.release_plan[0]!.amount).toBe(300);
  expect(source.benefits).toEqual(["完整功能体验"]);
  expect(
    catalogTemplateFields({ ...source, plan_type: "credit_pack" }).release_plan![0]!.account_type
  ).toBe("traffic_pack");
});

it("carries a custom duration into the catalog without creating a credit batch", () => {
  const source = {
    id: 9,
    entitlement_kind: "duration",
    plan_type: "subscription",
    billing_period_days: 90,
    total_credits: 0,
    release_plan: [],
    benefits: ["自配模型"],
    requires_active_subscription: false,
  } as unknown as PricingTemplate;
  const fields = catalogTemplateFields(source);
  expect(fields.entitlement_kind).toBe("duration");
  expect(fields.benefit_period_days).toBe(90);
  expect(fields.total_credits).toBe(0);
  expect(fields.release_plan).toEqual([]);
  expect(fields.requires_active_subscription).toBe(false);
});
