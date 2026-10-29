import { describe, expect, it } from "vitest";
import type { CatalogModel, ProviderAccount, ProviderTemplate } from "@/api/module_model_gateway";
import { isChatGatewayCompatible, sortCatalogModels, sortProviderTemplates } from "./model-order";

const model = (id: string, status: CatalogModel["status"] = "inactive") =>
  ({
    id: id.length,
    provider_account_id: 1,
    provider_model_id: id,
    display_name: id,
    supports_stream: true,
    supports_tools: false,
    supports_vision: false,
    supports_pdf: false,
    input_cost_per_million: 1,
    output_cost_per_million: 2,
    input_credits_per_1k: 1,
    output_credits_per_1k: 2,
    minimum_credits: 1,
    status,
  }) as CatalogModel;

describe("model resource ordering", () => {
  it("puts enabled suppliers before configured and unconfigured suppliers", () => {
    const templates = [
      { id: 1, name: "未配置", order: 1 } as ProviderTemplate,
      { id: 2, name: "已启用", order: 2 } as ProviderTemplate,
      { id: 3, name: "已配置", order: 3 } as ProviderTemplate,
    ];
    const accounts = new Map<number, ProviderAccount>([
      [2, { template_id: 2, status: "active" } as ProviderAccount],
      [3, { template_id: 3, status: "inactive" } as ProviderAccount],
    ]);
    expect(
      sortProviderTemplates(templates, (item) => accounts.get(item.id!)).map((item) => item.id)
    ).toEqual([2, 3, 1]);
  });

  it("puts enabled and newer model releases first", () => {
    const rows = [
      model("qwen-72b-chat"),
      model("qwen3.6-max-2026-04-01"),
      model("ZHIPU/GLM-5.3"),
      model("qwen3.7-max-2026-05-17"),
      model("qwen3.7-max-2026-06-08"),
      model("qwen3.8-flash"),
      model("qwen3-max", "active"),
    ];
    expect(sortCatalogModels(rows, "qwen3.7-max").map((item) => item.provider_model_id)).toEqual([
      "qwen3-max",
      "qwen3.8-flash",
      "qwen3.7-max-2026-06-08",
      "qwen3.7-max-2026-05-17",
      "qwen3.6-max-2026-04-01",
      "qwen-72b-chat",
      "ZHIPU/GLM-5.3",
    ]);
  });

  it("keeps non-chat resources out of the managed chat route", () => {
    expect(isChatGatewayCompatible("qwen3.7-max")).toBe(true);
    expect(isChatGatewayCompatible("qwen3-tts-flash")).toBe(false);
    expect(isChatGatewayCompatible("text-embedding-v4")).toBe(false);
    expect(isChatGatewayCompatible("wan2.6-t2v")).toBe(false);
  });
});
