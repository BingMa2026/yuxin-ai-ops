import dayjs from "dayjs";

export function billingColumnVisible(prop: unknown, localMode: boolean): boolean {
  if (prop === "available_credits" || prop === "pending_credits") return !localMode;
  if (prop === "subscription_expires_at" || prop === "remaining_duration") return localMode;
  return true;
}

export function remainingSubscriptionTime(
  expiresAt?: string,
  status?: string,
  now = Date.now()
): string {
  if (!expiresAt) return "未开通";
  const expiry = dayjs(expiresAt);
  if (!expiry.isValid()) return "—";
  const remaining = expiry.valueOf() - now;
  if (remaining <= 0 || status === "expired") return "已到期";
  if (status !== "active") return "已暂停";
  const days = Math.floor(remaining / 86_400_000);
  return days > 0 ? `${days} 天` : "不足 1 天";
}
