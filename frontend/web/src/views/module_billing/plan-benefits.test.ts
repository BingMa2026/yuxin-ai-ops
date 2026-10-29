import { describe, expect, it } from "vitest";
import { planBenefits } from "./plan-benefits";

describe("planBenefits", () => {
  it("removes historical quota and validity lines while preserving real benefits", () => {
    const benefits = [
      "300算力积分",
      "5,000算力积分",
      "50,000算力积分",
      "150,000算力积分",
      "500,000算力积分",
      " 59，000 算力积分 ",
      "5.9万积分",
      "有效期365天",
      "积分有效期：30天",
      "个人项目管理",
      "即时到账",
      "算力积分按计划释放",
      "7天完整功能体验",
      "每月赠送500积分",
      "支持500个项目",
    ];
    expect(planBenefits(benefits)).toEqual([
      "个人项目管理",
      "即时到账",
      "算力积分按计划释放",
      "7天完整功能体验",
      "每月赠送500积分",
      "支持500个项目",
    ]);
    expect(benefits).toHaveLength(15);
    expect(planBenefits([])).toEqual([]);
  });
});
