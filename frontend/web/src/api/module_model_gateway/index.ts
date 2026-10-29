import { request, type ExtendedRequestConfig } from "@utils";

export interface ProviderTemplate extends BaseType {
  max_timeout_seconds?: number;
  code: string;
  name: string;
  protocol: string;
  field_schema: { key: string; label: string; type: string; required: boolean; secret?: boolean }[];
  default_endpoint?: string;
  logo_key?: string;
  description?: string;
  recommended_model?: string;
  adapter_ready: boolean;
  custom: boolean;
  order: number;
  status: string;
}
export interface ProviderAccount extends BaseType {
  template_id: number;
  code: string;
  name: string;
  endpoint: string;
  masked_summary: Record<string, string>;
  timeout_seconds: number;
  retry_count: number;
  status: "active" | "inactive";
  connection_status: string;
  last_verified_at?: string;
  last_error?: string;
}
export interface SpeechPricing {
  region: string;
  currency: "CNY";
  source_url?: string | null;
  verified_at: string;
  note: string;
  items: {
    label: string;
    unit: "second" | "10k_characters" | "million_tokens" | "voice";
    price: string | number;
  }[];
}
export interface CatalogModel extends BaseType {
  speech_protocol?: string | null;
  speech_pricing?: SpeechPricing | null;
  provider_account_id: number;
  provider_model_id: string;
  display_name: string;
  context_length?: number;
  supports_stream: boolean;
  supports_tools: boolean;
  supports_vision: boolean;
  supports_pdf: boolean;
  input_cost_per_million: number;
  output_cost_per_million: number;
  cache_read_cost_per_million: number;
  cache_write_cost_per_million: number;
  reasoning_cost_per_million: number;
  price_version_id?: number;
  price_source?: string;
  input_credits_per_1k: number;
  output_credits_per_1k: number;
  minimum_credits: number;
  status: "active" | "inactive";
}
export interface ModelBinding extends BaseType {
  app_id: number;
  catalog_model_id: number;
  public_model_code: string;
  client_display_name: string;
  visible: boolean;
  user_selectable: boolean;
  is_default: boolean;
  input_credits_per_1k?: number;
  output_credits_per_1k?: number;
  fallback_binding_id?: number;
  order: number;
  status: "active" | "inactive";
}
export interface GenerationSettings {
  policy_version: "qwen3.8-bounded-v1";
  enable_thinking: boolean;
  thinking_budget_tokens: number;
  total_timeout_seconds: number;
  response_format: "text" | "json_object";
}
export interface ModelRoute extends BaseType {
  app_id: number;
  business_code: string;
  name: string;
  primary_binding_id: number;
  fallback_binding_ids: number[];
  timeout_seconds: number;
  max_output_tokens?: number;
  generation_settings?: GenerationSettings | null;
  allow_tools: boolean;
  allow_user_model: boolean;
  status: "active" | "inactive";
}
export interface FinanceProfile extends BaseType {
  provider_account_id: number;
  adapter_type: string;
  masked_summary: Record<string, string>;
  capabilities: Record<string, boolean>;
  balance_warning_yuan?: number;
  status: "active" | "inactive";
  connection_status: string;
  last_synced_at?: string;
  last_bill_at?: string;
  last_error?: string;
}
export interface FinanceSummary {
  profile?: FinanceProfile;
  latest_balance?: {
    currency: string;
    available_amount: number;
    amount_yuan?: number;
    fetched_at: string;
    source: string;
  };
  month_bill_yuan: number;
  last_bill_at?: string;
  request_cost_yuan: number;
  speech_cost_yuan: number;
  unknown_cost_calls: number;
  month_request_count?: number;
  difference_yuan: number;
  reconciliation_coverage_rate: number;
  resource_packages: {
    external_id: string;
    name: string;
    package_type?: string;
    total_amount: number;
    remaining_amount: number;
    unit: string;
    expires_at?: string;
    status: string;
    fetched_at: string;
  }[];
}
export interface PurchasePrice extends BaseType {
  provider_account_id: number;
  catalog_model_id: number;
  provider_model_id: string;
  region?: string;
  service_tier: string;
  billing_mode: string;
  context_min: number;
  context_max?: number;
  currency: string;
  exchange_rate_to_cny: number;
  input_cost_per_million: number;
  cache_read_cost_per_million: number;
  cache_write_cost_per_million: number;
  output_cost_per_million: number;
  reasoning_cost_per_million: number;
  source: string;
  effective_from: string;
  effective_until?: string;
  status: string;
}

const ModelGatewayAPI = {
  templates: () =>
    request<ApiResponse<ProviderTemplate[]>>({
      url: "/operations/models/provider-templates",
      method: "get",
    } as ExtendedRequestConfig),
  accounts: () =>
    request<ApiResponse<ProviderAccount[]>>({
      url: "/operations/models/provider-accounts",
      method: "get",
    } as ExtendedRequestConfig),
  createAccount: (data: Record<string, unknown>) =>
    request<ApiResponse<ProviderAccount>>({
      url: "/operations/models/provider-accounts",
      method: "post",
      data,
    } as ExtendedRequestConfig),
  updateAccount: (id: number, data: Record<string, unknown>) =>
    request<ApiResponse<ProviderAccount>>({
      url: `/operations/models/provider-accounts/${id}`,
      method: "put",
      data,
    } as ExtendedRequestConfig),
  testAccount: (id: number) =>
    request<ApiResponse<ProviderAccount>>({
      url: `/operations/models/provider-accounts/${id}/test`,
      method: "post",
    } as ExtendedRequestConfig),
  testConnection: (data: Record<string, unknown>) =>
    request<ApiResponse<{ provider_model_id: string; display_name: string }[]>>({
      url: "/operations/models/provider-accounts/test-connection",
      method: "post",
      data,
      showSuccessMessage: false,
    } as ExtendedRequestConfig),
  discoverModels: (id: number) =>
    request<
      ApiResponse<
        {
          provider_model_id: string;
          display_name: string;
          owned_by?: string;
          already_synced: boolean;
          price_matched: boolean;
          gateway_compatible: boolean;
        }[]
      >
    >({
      url: `/operations/models/provider-accounts/${id}/discover`,
      method: "post",
      showSuccessMessage: false,
    } as ExtendedRequestConfig),
  setAccountStatus: (id: number, status: ProviderAccount["status"]) =>
    request<ApiResponse<ProviderAccount>>({
      url: `/operations/models/provider-accounts/${id}/status`,
      method: "patch",
      data: { status },
      showSuccessMessage: false,
    } as ExtendedRequestConfig),
  financeSummary: (id: number) =>
    request<ApiResponse<FinanceSummary>>({
      url: `/operations/models/provider-accounts/${id}/finance`,
      method: "get",
    } as ExtendedRequestConfig),
  saveFinance: (id: number, data: Record<string, unknown>) =>
    request<ApiResponse<FinanceProfile>>({
      url: `/operations/models/provider-accounts/${id}/finance`,
      method: "put",
      data,
      showSuccessMessage: false,
    } as ExtendedRequestConfig),
  syncFinance: (id: number, data: Record<string, unknown> = {}) =>
    request<ApiResponse<FinanceSummary>>({
      url: `/operations/models/provider-accounts/${id}/finance/sync`,
      method: "post",
      data,
      showSuccessMessage: false,
    } as ExtendedRequestConfig),
  testFinance: (id: number) =>
    request<ApiResponse<FinanceProfile>>({
      url: `/operations/models/provider-accounts/${id}/finance/test`,
      method: "post",
      showSuccessMessage: false,
    } as ExtendedRequestConfig),
  prices: (id: number) =>
    request<ApiResponse<PurchasePrice[]>>({
      url: `/operations/models/provider-accounts/${id}/prices`,
      method: "get",
    }),
  createPrice: (id: number, data: Record<string, unknown>) =>
    request<ApiResponse<PurchasePrice>>({
      url: `/operations/models/provider-accounts/${id}/prices`,
      method: "post",
      data,
      showSuccessMessage: false,
    } as ExtendedRequestConfig),
  models: () =>
    request<ApiResponse<CatalogModel[]>>({ url: "/operations/models/catalog", method: "get" }),
  createModel: (data: Record<string, unknown>) =>
    request<ApiResponse<CatalogModel>>({ url: "/operations/models/catalog", method: "post", data }),
  updateModel: (id: number, data: Record<string, unknown>) =>
    request<ApiResponse<CatalogModel>>({
      url: `/operations/models/catalog/${id}`,
      method: "put",
      data,
    }),
  setModelStatus: (id: number, status: CatalogModel["status"]) =>
    request<ApiResponse<CatalogModel>>({
      url: `/operations/models/catalog/${id}/status`,
      method: "patch",
      data: { status },
      showSuccessMessage: false,
    } as ExtendedRequestConfig),
  bindings: () =>
    request<ApiResponse<ModelBinding[]>>({ url: "/operations/models/bindings", method: "get" }),
  createBinding: (data: Record<string, unknown>) =>
    request<ApiResponse<ModelBinding>>({
      url: "/operations/models/bindings",
      method: "post",
      data,
    }),
  updateBinding: (id: number, data: Record<string, unknown>) =>
    request<ApiResponse<ModelBinding>>({
      url: `/operations/models/bindings/${id}`,
      method: "put",
      data,
    }),
  setBindingStatus: (id: number, status: ModelBinding["status"]) =>
    request<ApiResponse<ModelBinding>>({
      url: `/operations/models/bindings/${id}/status`,
      method: "patch",
      data: { status },
      showSuccessMessage: false,
    } as ExtendedRequestConfig),
  routes: () =>
    request<ApiResponse<ModelRoute[]>>({ url: "/operations/models/routes", method: "get" }),
  saveRoute: (data: Record<string, unknown>) =>
    request<ApiResponse<ModelRoute>>({ url: "/operations/models/routes", method: "post", data }),
};

export default ModelGatewayAPI;
