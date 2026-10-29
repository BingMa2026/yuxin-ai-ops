import { describe, expect, it } from "vitest";
import { remainingSubscriptionTime } from "./billing-view";

describe("subscription time shown in user management", () => {
  const now = Date.parse("2026-10-10T08:00:00Z");

  it("distinguishes unopened subscriptions and invalid server dates", () => {
    expect(remainingSubscriptionTime(undefined, undefined, now)).toBe("未开通");
    expect(remainingSubscriptionTime("invalid", "active", now)).toBe("—");
  });

  it("shows remaining time without rounding a short period up to a full day", () => {
    expect(remainingSubscriptionTime("2026-10-11T07:59:59Z", "active", now)).toBe("不足 1 天");
    expect(remainingSubscriptionTime("2026-10-12T08:00:00Z", "active", now)).toBe("2 天");
  });

  it("does not show usable days at expiry or while the subscription is paused", () => {
    expect(remainingSubscriptionTime("2026-10-10T08:00:00Z", "active", now)).toBe("已到期");
    expect(remainingSubscriptionTime("2026-10-12T08:00:00Z", "cancelled", now)).toBe("已暂停");
  });
});
