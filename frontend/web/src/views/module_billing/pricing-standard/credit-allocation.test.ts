import { describe, expect, it } from "vitest";
import type { PricingVersionForm } from "@/api/module_billing";
import {
  creditsForPrice,
  distributeCredits,
  rebalanceReleases,
  updateDefaultCredits,
  updatePriceCredits,
} from "./credit-allocation";

function template(price = 9900, total = 99000): PricingVersionForm["templates"][number] {
  return {
    name: "基础版",
    code: "starter",
    plan_type: "subscription",
    tier_order: 1,
    billing_period_days: 30,
    one_time_price_fen: price,
    recurring_price_fen: price,
    total_credits: total,
    credit_valid_days: 30,
    benefits: [],
    requires_active_subscription: false,
    order: 1,
    release_plan: [0, 7, 14, 21].map((offset_day) => ({
      offset_day,
      amount: 1,
      account_type: "current_cycle",
    })),
  };
}

describe("pricing template automatic credits", () => {
  it("allocates integer remainders to earlier batches without losing credits", () => {
    expect(distributeCredits(99, 4)).toEqual([25, 25, 25, 24]);
    expect(distributeCredits(99000, 4)).toEqual([24750, 24750, 24750, 24750]);
    expect(distributeCredits(101, 4)).toEqual([26, 25, 25, 25]);
    expect(distributeCredits(99, 1)).toEqual([99]);
  });
  it("converts prices with the configured rate and rounds to whole credits", () => {
    expect(creditsForPrice(9900, 1000)).toBe(99000);
    expect(creditsForPrice(9900, 500)).toBe(49500);
    expect(creditsForPrice(9999, 125)).toBe(12499);
  });
  it("rebalances on price, total and batch-count changes, preserving dates and accounts", () => {
    const plan = template();
    plan.release_plan[1]!.account_type = "monthly_reserve";
    expect(updatePriceCredits(plan, 1000)).toBe(true);
    expect(plan.release_plan.map((r) => r.amount)).toEqual([24750, 24750, 24750, 24750]);
    plan.total_credits = 99;
    rebalanceReleases(plan);
    expect(plan.release_plan.map((r) => r.amount)).toEqual([25, 25, 25, 24]);
    expect(plan.release_plan.map((r) => r.offset_day)).toEqual([0, 7, 14, 21]);
    expect(plan.release_plan[1]!.account_type).toBe("monthly_reserve");
    plan.release_plan.splice(3, 1);
    rebalanceReleases(plan);
    expect(plan.release_plan.map((r) => r.amount)).toEqual([33, 33, 33]);
  });
  it("retains custom credits and free-trial credits when the default rate changes", () => {
    const automatic = template();
    const custom = template(9900, 120000);
    const trial = template(0, 300);
    updateDefaultCredits([automatic, custom, trial], 1000, 500);
    expect(automatic.total_credits).toBe(49500);
    expect(custom.total_credits).toBe(120000);
    expect(trial.total_credits).toBe(300);
    updatePriceCredits(trial, 1000);
    expect(trial.total_credits).toBe(300);
  });
  it("rejects invalid totals rather than producing zero or fractional batches", () => {
    for (const total of [0, 3, 99.5, NaN, Infinity]) expect(distributeCredits(total, 4)).toBeNull();
    expect(distributeCredits(99, 0)).toBeNull();
    const plan = template(1, 3);
    expect(rebalanceReleases(plan)).toBe(false);
    expect(plan.release_plan.map((r) => r.amount)).toEqual([1, 1, 1, 1]);
  });
});

it("does not add credits to a duration product when changing price or global conversion", () => {
  const plan = {
    ...template(),
    entitlement_kind: "duration" as const,
    total_credits: 0,
    release_plan: [],
  };
  plan.one_time_price_fen = 19900;
  updatePriceCredits(plan, 1000);
  updateDefaultCredits([plan], 1000, 500);
  expect(plan.total_credits).toBe(0);
  expect(plan.release_plan).toEqual([]);
});
