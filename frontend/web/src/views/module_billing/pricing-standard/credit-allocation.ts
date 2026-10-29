import type { PricingVersionForm } from "@/api/module_billing";

type Template = PricingVersionForm["templates"][number];

export function creditsForPrice(priceFen: number, creditsPerYuan: number): number {
  return Math.round((priceFen * creditsPerYuan) / 100);
}

export function distributeCredits(total: number, count: number): number[] | null {
  if (!Number.isSafeInteger(total) || !Number.isSafeInteger(count) || count < 1 || total < count)
    return null;
  const base = Math.floor(total / count);
  const remainder = total % count;
  return Array.from({ length: count }, (_, index) => base + (index < remainder ? 1 : 0));
}

export function rebalanceReleases(template: Template): boolean {
  const amounts = distributeCredits(template.total_credits, template.release_plan.length);
  if (!amounts) return false;
  template.release_plan.forEach((release, index) => (release.amount = amounts[index]!));
  return true;
}

export function updatePriceCredits(template: Template, creditsPerYuan: number): boolean {
  if (template.entitlement_kind === "duration") return true;
  // Free trials keep their manually configured credits; opening a template never recalculates it.
  if (template.one_time_price_fen <= 0) return true;
  template.total_credits = creditsForPrice(template.one_time_price_fen, creditsPerYuan);
  return rebalanceReleases(template);
}

export function updateDefaultCredits(
  templates: Template[],
  oldRate: number,
  newRate: number
): void {
  for (const template of templates) {
    if (
      template.one_time_price_fen > 0 &&
      template.total_credits === creditsForPrice(template.one_time_price_fen, oldRate)
    )
      updatePriceCredits(template, newRate);
  }
}
