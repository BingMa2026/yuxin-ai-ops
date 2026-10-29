import { request } from "@utils";

const API_PATH = "/payment/channel";

export type PaymentProvider = "wechat" | "alipay";
export type PaymentMode = "sandbox" | "production";

export interface PaymentChannel extends BaseType {
  provider: PaymentProvider;
  name: string;
  enabled: boolean;
  mode: PaymentMode;
  fee_rate: number;
  settlement_cycle: string;
  scenes: string[];
  description?: string;
  order: number;
  configured: boolean;
  missing_fields: string[];
  merchant_identity?: string;
  notify_url_configured: boolean;
  environment_fields: string[];
  app_enabled: boolean;
}

export interface PaymentChannelForm extends BaseFormType {
  name: string;
  mode: PaymentMode;
  fee_rate: number;
  settlement_cycle: string;
  scenes: string[];
  description?: string;
  order: number;
}

const PaymentChannelAPI = {
  list() {
    return request<ApiResponse<PaymentChannel[]>>({
      url: `${API_PATH}/list`,
      method: "get",
    });
  },
  update(provider: PaymentProvider, body: Partial<PaymentChannelForm>) {
    return request<ApiResponse<PaymentChannel>>({
      url: `${API_PATH}/update/${provider}`,
      method: "put",
      data: body,
    });
  },
  toggle(provider: PaymentProvider, enabled: boolean) {
    return request<ApiResponse<PaymentChannel>>({
      url: `${API_PATH}/toggle/${provider}`,
      method: "put",
      data: { enabled },
    });
  },
  bind(provider: PaymentProvider, enabled: boolean) {
    return request<ApiResponse<PaymentChannel>>({
      url: `${API_PATH}/bind/${provider}`,
      method: "put",
      data: { enabled },
    });
  },
};

export default PaymentChannelAPI;
