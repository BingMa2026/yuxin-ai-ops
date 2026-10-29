import type { CatalogPlanForm, PricingTemplate } from "@/api/module_billing";

export function catalogTemplateFields(item: PricingTemplate): Partial<CatalogPlanForm> {
  return {
    template_id: item.id,
    entitlement_kind: item.entitlement_kind ?? "credits",
    code: item.code,
    name: item.name,
    plan_type: item.plan_type,
    tier_code: item.tier_code,
    tier_order: item.tier_order,
    one_time_price_fen: item.one_time_price_fen,
    recurring_price_fen: item.recurring_price_fen,
    benefit_period_days: item.billing_period_days,
    total_credits: item.total_credits,
    release_plan: item.release_plan.map((release) => ({
      ...release,
      account_type:
        release.account_type ||
        (item.plan_type === "credit_pack" ? "traffic_pack" : "current_cycle"),
    })),
    credit_valid_days: item.credit_valid_days,
    benefits: [...item.benefits],
    requires_active_subscription:
      item.requires_active_subscription || item.plan_type === "credit_pack",
    order: item.order,
  };
}
